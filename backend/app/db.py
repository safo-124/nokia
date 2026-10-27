"""PostgreSQL connection pool, opened on first use.

Set DATABASE_URL to point somewhere else than the local default.
"""

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/signal_to_rain"

_pool = None


def database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def configure(url):
    """Point the pool at another database (used by the tests)."""
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = ConnectionPool(url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True)


def query(sql, params=None, one=False):
    if _pool is None:
        configure(database_url())
    with _pool.connection(timeout=5) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
