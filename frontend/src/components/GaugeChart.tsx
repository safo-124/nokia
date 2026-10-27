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

import type { DatasetApi } from "../api";
import { SERIES } from "../colors";
import type { GaugeComparison } from "../types";

const hhmm = (t: unknown) => String(t).slice(11, 16);

interface Props {
  dataset: DatasetApi;
  gaugeId: string | null;
  currentTime: string;
  dark: boolean;
}

export default function GaugeChart({ dataset, gaugeId, currentTime, dark }: Props) {
  const [data, setData] = useState<GaugeComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const colors = SERIES[dark ? "dark" : "light"];

  useEffect(() => {
    if (!gaugeId) return;
    let cancelled = false;
    setData(null);
    dataset
      .gaugeComparison(gaugeId)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [dataset, gaugeId]);

  const rows = useMemo(
    () => data?.time.map((t, i) => ({ t, gauge: data.gauge[i], estimate: data.estimate[i] })) ?? [],
    [data],
  );
  // The chart is in 15-minute steps; mark the step that contains the replay time
  const marker = useMemo(() => rows.findLast((r) => r.t <= currentTime)?.t, [rows, currentTime]);

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
            <XAxis
              dataKey="t"
              tickFormatter={hhmm}
              tick={{ fill: colors.axis, fontSize: 11 }}
              stroke={colors.grid}
              minTickGap={24}
            />
            <YAxis tick={{ fill: colors.axis, fontSize: 11 }} stroke={colors.grid} />
            <Tooltip
              labelFormatter={hhmm}
              formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)} mm/h` : "–")}
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--ink)",
                fontSize: 12,
              }}
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
        {stats.total_estimate_mm} mm ({data.minutes}-minute means, mm/h)
      </p>
    </div>
  );
}
