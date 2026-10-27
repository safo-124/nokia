import { RISK } from "../colors";
import { arrival } from "../sms";
import type { Alert } from "../types";

interface Props {
  alerts: Alert[];
  currentTime: string;
  hasFloodRisk: boolean;
}

function AlertCard({ alert: a }: { alert: Alert }) {
  const forecast = a.kind === "forecast";
  return (
    <li
      className="rounded-md border p-2 text-sm"
      style={{ borderColor: forecast ? RISK[a.level].color : "var(--border)", borderStyle: forecast ? "dashed" : "solid" }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-medium">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: RISK[a.level].color }} />
          {forecast
            ? `Early warning · ${RISK[a.level].label} in ${a.eta_low_min != null ? "" : "~"}${arrival(a).replace("-", "–")} min`
            : `${RISK[a.level].label} now`}
          {" · "}
          {a.name}
        </span>
        <span className="tabular text-xs text-[var(--muted)]">{a.time.slice(11, 16)}</span>
      </div>
      <p className="mt-1 text-[var(--ink-2)]">{a.message}</p>
    </li>
  );
}

export default function AlertPanel({ alerts, currentTime, hasFloodRisk }: Props) {
  if (!hasFloodRisk) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No flood hotspots for this region. Run the pipeline with --hotspots to add them.
      </p>
    );
  }
  const issued = alerts.filter((a) => a.time <= currentTime).reverse();
  if (issued.length === 0) {
    return <p className="text-sm text-[var(--muted)]">No alerts yet. Press play to replay the storm.</p>;
  }
  return (
    <ul className="space-y-2">
      {issued.map((a) => (
        <AlertCard key={`${a.hotspot_id}-${a.kind}-${a.level}-${a.time}`} alert={a} />
      ))}
    </ul>
  );
}
