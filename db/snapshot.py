"""Save or load the demo datasets as one file, so every laptop has the same data without running the pipeline.

    python db/snapshot.py save     # writes db/demo_snapshot.zip from your database
    python db/snapshot.py load     # loads it into yours, creating the database and tables if needed

Options: --file PATH to use another file, --dataset NAME (repeatable) to save only some datasets.
Loading replaces the datasets that are in the file and leaves any others alone.

Needs only psycopg (in backend/requirements.txt). Connects to DATABASE_URL like
the rest of the project, default postgresql://postgres:postgres@localhost:5432/signal_to_rain.
"""

import argparse
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema.sql"
DEFAULT_FILE = HERE / "demo_snapshot.zip"
DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/signal_to_rain"
# Parents first, so foreign keys hold while loading
TABLES = ["datasets", "links", "link_rain", "rain_grid", "gauges", "gauge_rain", "hotspots", "flood_risk", "alerts"]


def connect(url):
    """Connect, creating the database first if it doesn't exist (same as pipeline/s2r/db.py)."""
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            raise
    name = conninfo_to_dict(url)["dbname"]
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return psycopg.connect(url)


def _key(table):
    return "id" if table == "datasets" else "dataset"


def save(conn, path, datasets=None):
    ids = datasets or [r[0] for r in conn.execute("SELECT id FROM datasets ORDER BY created_at")]
    if not ids:
        raise SystemExit("No datasets in the database. Run the pipeline first: cd pipeline && python -m s2r.run")
    counts = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for table in TABLES:
            stmt = sql.SQL("COPY (SELECT * FROM {} WHERE {} = ANY({}) ORDER BY 1, 2) TO STDOUT (FORMAT csv, HEADER)").format(
                sql.Identifier(table), sql.Identifier(_key(table)), sql.Literal(ids)
            )
            with zf.open(f"{table}.csv", "w", force_zip64=True) as f, conn.cursor().copy(stmt) as copy:
                for chunk in copy:
                    f.write(chunk)
            counts[table] = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE {} = ANY(%s)").format(sql.Identifier(table), sql.Identifier(_key(table))),
                (ids,),
            ).fetchone()[0]
        zf.writestr("manifest.json", json.dumps({
            "datasets": ids,
            "rows": counts,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=1))
    return ids, counts


def load(conn, path):
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        with conn.transaction():
            conn.execute(SCHEMA.read_text(encoding="utf-8"))
            conn.execute("DELETE FROM datasets WHERE id = ANY(%s)", (manifest["datasets"],))
            for table in TABLES:
                with zf.open(f"{table}.csv") as f:
                    # Load by column name, so older or newer column orders still line up
                    columns = f.readline().decode("utf-8").strip().split(",")
                    stmt = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv)").format(
                        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
                    )
                    with conn.cursor().copy(stmt) as copy:
                        while chunk := f.read(1 << 20):
                            copy.write(chunk)
            for table, expected in manifest["rows"].items():
                got = conn.execute(
                    sql.SQL("SELECT count(*) FROM {} WHERE {} = ANY(%s)").format(sql.Identifier(table), sql.Identifier(_key(table))),
                    (manifest["datasets"],),
                ).fetchone()[0]
                if got != expected:
                    raise SystemExit(f"{table}: loaded {got} rows, the snapshot has {expected}. Nothing was changed.")
    return manifest


def main():
    p = argparse.ArgumentParser(description="Save or load the Signal-to-Rain demo datasets")
    p.add_argument("action", choices=["save", "load"])
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--dataset", action="append", help="save only this dataset (repeatable)")
    args = p.parse_args()
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)

    with connect(url) as conn:
        if args.action == "save":
            ids, counts = save(conn, args.file, args.dataset)
            size = args.file.stat().st_size / 1e6
            print(f"Saved {', '.join(ids)} ({sum(counts.values()):,} rows) to {args.file} ({size:.1f} MB)")
        else:
            if not args.file.exists():
                raise SystemExit(f"{args.file} not found. Ask a teammate for it, or run the pipeline instead.")
            m = load(conn, args.file)
            print(f"Loaded {', '.join(m['datasets'])} ({sum(m['rows'].values()):,} rows, saved {m['saved_at']}) "
                  f"into {conninfo_to_dict(url)['dbname']}")


if __name__ == "__main__":
    main()
