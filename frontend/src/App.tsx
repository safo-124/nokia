import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "./api";
import { usePrefersDark } from "./colors";
import AlertPanel from "./components/AlertPanel";
import GaugeChart from "./components/GaugeChart";
import PhoneMockup from "./components/PhoneMockup";
import RainMap from "./components/RainMap";
import ReplayControls from "./components/ReplayControls";
import type { Language } from "./sms";
import type {
  Alert,
  DatasetSummary,
  FloodRisk,
  Gauges,
  GridFrame,
  Hotspots,
  Lead,
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

function NowcastScores({ nowcast }: { nowcast: Meta["nowcast"] }) {
  if (!nowcast) return <p className="text-sm text-[var(--muted)]">Re-run the pipeline to add the nowcast.</p>;
  const w = nowcast.warnings;
  return (
    <div className="space-y-3 text-sm">
      {w && (
        <p>
          <span className="tabular">{w.hits}</span> of <span className="tabular">{w.warnings}</span> early warnings came
          true, a median of <strong className="tabular">{w.median_lead_min ?? "–"} min</strong> before the level was
          reached. {w.false_alarms} false alarms, {w.missed} missed.
        </p>
      )}
      {w?.median_eta_error_min != null && (
        <p>
          Stated arrival time off by a median of <span className="tabular">{w.median_eta_error_min} min</span>
          {w.eta_in_range != null && (
            <>
              ; the level was reached inside the stated time range in{" "}
              <span className="tabular">{Math.round(w.eta_in_range * 100)}%</span> of cases
            </>
          )}
          .
        </p>
      )}
      <p className="text-xs text-[var(--muted)]">
        Storm motion is tracked with a Kalman filter, which also gives the ± on the speed and the time ranges on
        warnings.
      </p>
      <table className="tabular w-full">
        <caption className="mb-1 text-left text-xs text-[var(--muted)]">
          Rain above {nowcast.skill[0]?.threshold_mm_h} mm/h hit where forecast (CSI, higher is better)
        </caption>
        <thead className="text-left text-xs text-[var(--muted)]">
          <tr>
            <th className="font-normal">Ahead</th>
            <th className="font-normal">Nowcast</th>
            <th className="font-normal">Rain stays put</th>
          </tr>
        </thead>
        <tbody>
          {nowcast.skill.map((s) => (
            <tr key={s.lead_min}>
              <td>+{s.lead_min} min</td>
              <td>{s.csi.nowcast ?? "–"}</td>
              <td>{s.csi.persistence ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QualityNote({ quality }: { quality: Meta["quality"] }) {
  if (!quality) return <p className="text-sm text-[var(--muted)]">Re-run the pipeline to add quality checks.</p>;
  const reasons = Object.entries(quality.by_reason);
  return (
    <div className="space-y-1 text-sm">
      <p>
        <span className="tabular">{quality.excluded}</span> of <span className="tabular">{quality.links}</span> links
        left out of the map{reasons.length > 0 && ":"}
      </p>
      {reasons.length > 0 && (
        <ul className="tabular list-disc pl-5 text-[var(--ink-2)]">
          {reasons.map(([reason, n]) => (
            <li key={reason}>
              {n} {reason}
            </li>
          ))}
        </ul>
      )}
      {quality.readings_removed > 0 && (
        <p className="text-[var(--ink-2)]">{quality.readings_removed} impossible readings removed from other links.</p>
      )}
      <p className="text-xs text-[var(--muted)]">Hover a dashed grey link to see why it was left out.</p>
    </div>
  );
}

function WetDryScores({ scores, method }: { scores: Meta["wet_dry_scores"]; method: Meta["wet_dry_method"] }) {
  const used = method === "ml" ? "AI classifier" : "rolling std rule";
  if (!scores) {
    return <p className="text-sm text-[var(--muted)]">No reference data to score against. The map uses the {used}.</p>;
  }
  const rows: [string, WetDryScore][] = [
    ["Rolling std rule", scores.rolling_std],
    ["AI classifier", scores.ml],
  ];
  return (
    <>
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
      <p className="mt-2 text-xs text-[var(--muted)]">
        The AI classifier also looks at what nearby links are doing. The rain map uses the {used}.
      </p>
    </>
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
  const [lead, setLead] = useState<Lead>(0);
  const [frame, setFrame] = useState<Frame>({});
  const [selectedGauge, setSelectedGauge] = useState<string | null>(null);
  const [phoneHotspot, setPhoneHotspot] = useState<string | null>(null);
  const [smsLang, setSmsLang] = useState<Language>("en");

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
      // Start the phone in the neighbourhood that is warned first
      setPhoneHotspot(alerts[0]?.hotspot_id ?? hotspots?.features[0]?.properties.id ?? null);
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
      dataset.grid(currentTime, lead),
      dataset.linkRain(currentTime),
      meta.has_flood_risk ? dataset.floodRisk(currentTime) : null,
    ])
      .then(([grid, linkRain, risk]) => !cancelled && setFrame({ grid, linkRain, risk }))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [dataset, meta, currentTime, lead]);

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
              selectedHotspot={phoneHotspot}
              onSelectHotspot={setPhoneHotspot}
              dark={dark}
            />
          </div>
          <ReplayControls
            times={meta.times}
            index={index}
            onIndex={setIndex}
            playing={playing}
            onPlaying={setPlaying}
            lead={lead}
            onLead={setLead}
          />
        </main>

        <aside className="w-full overflow-y-auto border-l border-[var(--border)] bg-[var(--surface)] lg:w-96">
          {layers.hotspots && phoneHotspot && (
            <Section title="What a resident receives (SMS)">
              <PhoneMockup
                alerts={layers.alerts}
                hotspots={layers.hotspots}
                hotspotId={phoneHotspot}
                onHotspot={setPhoneHotspot}
                currentTime={currentTime}
                lang={smsLang}
                onLang={setSmsLang}
              />
            </Section>
          )}
          <Section title={`Alerts (${issued})`}>
            <AlertPanel alerts={layers.alerts} currentTime={currentTime} hasFloodRisk={meta.has_flood_risk} />
          </Section>
          <Section title="Nowcast (how well it predicts)">
            <NowcastScores nowcast={meta.nowcast} />
          </Section>
          <Section title={`Validation: gauge ${selectedGauge ?? ""}`}>
            <GaugeChart dataset={dataset} gaugeId={selectedGauge} currentTime={currentTime} dark={dark} />
          </Section>
          <Section title="Wet/dry classification (held-out links)">
            <WetDryScores scores={meta.wet_dry_scores} method={meta.wet_dry_method} />
          </Section>
          <Section title="Data quality">
            <QualityNote quality={meta.quality} />
          </Section>
        </aside>
      </div>
    </div>
  );
}
