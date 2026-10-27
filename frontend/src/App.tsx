import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "./api";
import { usePrefersDark } from "./colors";
import AlertPanel from "./components/AlertPanel";
import GaugeChart from "./components/GaugeChart";
import RainMap from "./components/RainMap";
import ReplayControls from "./components/ReplayControls";
import type {
  Alert,
  DatasetSummary,
  FloodRisk,
  Gauges,
  GridFrame,
  Hotspots,
  LinkRain,
  Links,
  Meta,
  WetDryScore,
} from "./types";

const STEP_MS = 120;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-[var(--border)] p-4">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function WetDryScores({ scores }: { scores: Meta["wet_dry_scores"] }) {
  if (!scores) return <p className="text-sm text-[var(--muted)]">No reference data to score against.</p>;
  const rows: [string, WetDryScore][] = [
    ["Rolling std rule", scores.rolling_std],
    ["AI classifier", scores.ml],
  ];
  return (
    <table className="tabular w-full text-sm">
      <thead className="text-left text-xs text-[var(--muted)]">
        <tr>
          <th className="font-normal">Method</th>
          <th className="font-normal">Accuracy</th>
          <th className="font-normal">MCC</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([name, s]) => (
          <tr key={name}>
            <td>{name}</td>
            <td>{s.accuracy}</td>
            <td>{s.mcc}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface StaticLayers {
  meta: Meta;
  links: Links;
  gauges: Gauges;
  hotspots: Hotspots | null;
  alerts: Alert[];
}

interface Frame {
  grid?: GridFrame;
  linkRain?: LinkRain;
  risk?: FloodRisk | null;
}

export default function App() {
  const dark = usePrefersDark();
  const [error, setError] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [layers, setLayers] = useState<StaticLayers | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState<Frame>({});
  const [selectedGauge, setSelectedGauge] = useState<string | null>(null);

  const dataset = useMemo(() => (datasetId ? api.dataset(datasetId) : null), [datasetId]);

  useEffect(() => {
    api
      .datasets()
      .then((list) => {
        if (list.length === 0) throw new Error("No datasets yet. Run the pipeline: cd pipeline && python -m s2r.run");
        setDatasets(list);
        setDatasetId(list[0].id);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // Static layers, loaded once per dataset
  useEffect(() => {
    if (!dataset) return;
    let cancelled = false;
    setLayers(null);
    setFrame({});
    setIndex(0);
    setPlaying(false);
    (async () => {
      const [meta, links, gauges] = await Promise.all([dataset.meta(), dataset.links(), dataset.gauges()]);
      const [hotspots, alerts] = meta.has_flood_risk
        ? await Promise.all([dataset.hotspots(), dataset.alerts()])
        : [null, []];
      if (cancelled) return;
      setLayers({ meta, links, gauges, hotspots, alerts });
      setSelectedGauge(gauges.features[0]?.properties.id ?? null);
    })().catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [dataset]);

  // Everything that changes with the replay time
  const meta = layers?.meta;
  const currentTime = meta?.times[index];
  useEffect(() => {
    if (!dataset || !meta || !currentTime) return;
    let cancelled = false;
    Promise.all([
      dataset.grid(currentTime),
      dataset.linkRain(currentTime),
      meta.has_flood_risk ? dataset.floodRisk(currentTime) : null,
    ])
      .then(([grid, linkRain, risk]) => !cancelled && setFrame({ grid, linkRain, risk }))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [dataset, meta, currentTime]);

  useEffect(() => {
    if (!playing || !meta) return;
    const last = meta.times.length - 1;
    if (index >= last) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => setIndex((i) => Math.min(i + 1, last)), STEP_MS);
    return () => clearTimeout(id);
  }, [playing, index, meta]);

  if (error) {
    return (
      <div className="m-6 rounded-md border border-[#d03b3b] p-4 text-sm">
        <strong>Could not load data.</strong> {error}
      </div>
    );
  }
  if (!dataset || !layers || !meta || !currentTime) {
    return <div className="p-6 text-sm text-[var(--muted)]">Loading…</div>;
  }

  const issued = layers.alerts.filter((a) => a.time <= currentTime).length;
  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <h1 className="text-lg font-semibold">Signal-to-Rain</h1>
        <select
          value={datasetId ?? ""}
          onChange={(e) => setDatasetId(e.target.value)}
          className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm"
          aria-label="Dataset"
        >
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.region} ({d.id})
            </option>
          ))}
        </select>
        <span className="text-sm text-[var(--ink-2)]">
          {meta.source} data · {meta.n_links} links · {meta.n_gauges} gauges
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <main className="flex min-h-[60vh] flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <RainMap
              meta={meta}
              links={layers.links}
              linkRain={frame.linkRain}
              grid={frame.grid}
              gauges={layers.gauges}
              hotspots={layers.hotspots}
              risk={frame.risk}
              selectedGauge={selectedGauge}
              onSelectGauge={setSelectedGauge}
              dark={dark}
            />
          </div>
          <ReplayControls
            times={meta.times}
            index={index}
            onIndex={setIndex}
            playing={playing}
            onPlaying={setPlaying}
          />
        </main>

        <aside className="w-full overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] lg:w-96">
          <Section title={`Alerts (${issued})`}>
            <AlertPanel alerts={layers.alerts} currentTime={currentTime} hasFloodRisk={meta.has_flood_risk} />
          </Section>
          <Section title={`Validation: gauge ${selectedGauge ?? ""}`}>
            <GaugeChart dataset={dataset} gaugeId={selectedGauge} currentTime={currentTime} dark={dark} />
          </Section>
          <Section title="Wet/dry classification (held-out links)">
            <WetDryScores scores={meta.wet_dry_scores} />
          </Section>
        </aside>
      </div>
    </div>
  );
}
