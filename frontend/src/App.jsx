import { useEffect, useState } from "react";

import { api } from "./api";
import { usePrefersDark } from "./colors";
import AlertPanel from "./components/AlertPanel";
import GaugeChart from "./components/GaugeChart";
import RainMap from "./components/RainMap";
import ReplayControls from "./components/ReplayControls";

const STEP_MS = 120;

function Section({ title, children }) {
  return (
    <section className="border-b border-[var(--border)] p-4">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function WetDryScores({ scores }) {
  if (!scores) return <p className="text-sm text-[var(--muted)]">No reference data to score against.</p>;
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
        <tr>
          <td>Rolling std rule</td>
          <td>{scores.rolling_std.accuracy}</td>
          <td>{scores.rolling_std.mcc}</td>
        </tr>
        <tr>
          <td>AI classifier</td>
          <td>{scores.ml.accuracy}</td>
          <td>{scores.ml.mcc}</td>
        </tr>
      </tbody>
    </table>
  );
}

export default function App() {
  const dark = usePrefersDark();
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);
  const [links, setLinks] = useState(null);
  const [gauges, setGauges] = useState(null);
  const [hotspots, setHotspots] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState({});
  const [selectedGauge, setSelectedGauge] = useState(null);

  // Static layers, loaded once
  useEffect(() => {
    Promise.all([api.meta(), api.links(), api.gauges()])
      .then(async ([m, l, g]) => {
        setMeta(m);
        setLinks(l);
        setGauges(g);
        setSelectedGauge(g.features[0]?.properties.id ?? null);
        if (m.has_flood_risk) {
          const [h, a] = await Promise.all([api.hotspots(), api.alerts()]);
          setHotspots(h);
          setAlerts(a);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  // Everything that changes with the replay time
  const currentTime = meta?.times[index];
  useEffect(() => {
    if (!currentTime) return;
    let cancelled = false;
    Promise.all([
      api.grid(currentTime),
      api.linkRain(currentTime),
      meta.has_flood_risk ? api.floodRisk(currentTime) : null,
    ])
      .then(([grid, linkRain, risk]) => !cancelled && setFrame({ grid, linkRain, risk }))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [meta, currentTime]);

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
  if (!meta) return <div className="p-6 text-sm text-[var(--muted)]">Loading…</div>;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-baseline gap-x-4 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <h1 className="text-lg font-semibold">Signal-to-Rain</h1>
        <span className="text-sm text-[var(--ink-2)]">
          {meta.region} · {meta.source} data · {meta.n_links} links · {meta.n_gauges} gauges
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <main className="flex min-h-[60vh] flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <RainMap
              meta={meta}
              links={links}
              linkRain={frame.linkRain}
              grid={frame.grid}
              gauges={gauges}
              hotspots={hotspots}
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
          <Section title={`Alerts (${alerts.filter((a) => a.time <= currentTime).length})`}>
            <AlertPanel alerts={alerts} currentTime={currentTime} hasFloodRisk={meta.has_flood_risk} />
          </Section>
          <Section title={`Validation: gauge ${selectedGauge ?? ""}`}>
            <GaugeChart gaugeId={selectedGauge} currentTime={currentTime} dark={dark} />
          </Section>
          <Section title="Wet/dry classification (held-out links)">
            <WetDryScores scores={meta.wet_dry_scores} />
          </Section>
        </aside>
      </div>
    </div>
  );
}
