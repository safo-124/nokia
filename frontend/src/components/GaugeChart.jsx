import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api";
import { SERIES } from "../colors";

const hhmm = (t) => t.slice(11, 16);

export default function GaugeChart({ gaugeId, currentTime, dark }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const colors = SERIES[dark ? "dark" : "light"];

  useEffect(() => {
    if (!gaugeId) return;
    let cancelled = false;
    api
      .gaugeComparison(gaugeId)
      .then((d) => !cancelled && (setData(d), setError(null)))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [gaugeId]);

  const rows = useMemo(
    () => data?.time.map((t, i) => ({ t, gauge: data.gauge[i], estimate: data.estimate[i] })) ?? [],
    [data],
  );
  // The chart is in 15-minute steps; mark the step that contains the replay time
  const marker = useMemo(() => [...rows].reverse().find((r) => r.t <= currentTime)?.t, [rows, currentTime]);

  if (!gaugeId) return <p className="text-sm text-[var(--muted)]">Click a gauge on the map.</p>;
  if (error) return <p className="text-sm text-[#d03b3b]">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--muted)]">Loading…</p>;

  const { stats } = data;
  return (
    <div>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke={colors.grid} vertical={false} />
            <XAxis dataKey="t" tickFormatter={hhmm} tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} minTickGap={24} />
            <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} unit="" />
            <Tooltip
              labelFormatter={hhmm}
              formatter={(v) => (v == null ? "–" : `${v.toFixed(1)} mm/h`)}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)", fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: "var(--ink-2)" }} />
            {marker && <ReferenceLine x={marker} stroke={colors.axis} strokeDasharray="3 3" />}
            <Line type="monotone" dataKey="gauge" name="Rain gauge" stroke={colors.gauge} strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="estimate" name="From links" stroke={colors.estimate} strokeWidth={2} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="tabular mt-1 text-xs text-[var(--ink-2)]">
        Correlation {stats.correlation ?? "–"} · gauge {stats.total_gauge_mm} mm · links{" "}
        {stats.total_estimate_mm} mm (15-minute means, mm/h)
      </p>
    </div>
  );
}
