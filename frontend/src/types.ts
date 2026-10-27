// Shapes of the API responses (see backend/app/main.py)
import type { FeatureCollection, LineString, Point } from "geojson";

export type Level = "low" | "medium" | "high";

export interface WetDryScore {
  accuracy: number;
  mcc: number;
}

export interface DatasetSummary {
  id: string;
  source: string;
  region: string;
  n_links: number;
  has_flood_risk: boolean;
  generated_at: string;
}

export interface NowcastSkill {
  lead_min: number;
  threshold_mm_h: number;
  /** Critical success index (0 to 1, higher is better) */
  csi: { nowcast: number | null; persistence: number | null };
}

export interface WarningPerformance {
  warnings: number;
  hits: number;
  false_alarms: number;
  missed: number;
  median_lead_min: number | null;
  min_lead_min: number | null;
  /** How far the stated arrival time was from when the level was reached */
  median_eta_error_min?: number | null;
  /** Share of hits where the level was reached inside the stated range */
  eta_in_range?: number | null;
}

export interface Meta extends DatasetSummary {
  bounds: [latMin: number, latMax: number, lonMin: number, lonMax: number];
  times: string[];
  n_gauges: number;
  wet_dry_method: "std" | "ml";
  wet_dry_scores: { rolling_std: WetDryScore; ml: WetDryScore } | null;
  nowcast?: { skill: NowcastSkill[]; warnings?: WarningPerformance | null };
  quality?: QualitySummary;
}

export type Links = FeatureCollection<
  LineString,
  {
    id: string;
    length_km: number;
    frequency_ghz: number;
    polarization: string;
    /** Failed a quality check; its rain is left out of the map */
    excluded: boolean;
    exclude_reason: string | null;
  }
>;

export interface QualitySummary {
  links: number;
  excluded: number;
  by_reason: Record<string, number>;
  readings_removed: number;
}
export type Gauges = FeatureCollection<Point, { id: string }>;
export type Hotspots = FeatureCollection<Point, { id: string; name: string; vulnerability: number }>;

export interface LinkRain {
  time: string;
  rain_rate: Record<string, number | null>;
}

export interface GridFrame {
  time: string;
  /** 0 for the observed map, otherwise minutes of nowcast after `time` */
  lead_min: number;
  valid_time: string;
  /** Storm motion from the Kalman filter; speed_sd_kmh is one standard deviation */
  motion: { speed_kmh: number; bearing_deg: number; speed_sd_kmh: number | null };
  lat: number[];
  lon: number[];
  /** Rows run south to north; null where no link is close enough */
  rain_rate: (number | null)[][];
}

export interface GaugeComparison {
  gauge_id: string;
  minutes: number;
  time: string[];
  gauge: (number | null)[];
  estimate: (number | null)[];
  stats: { correlation: number | null; total_gauge_mm: number; total_estimate_mm: number };
}

export interface HotspotRisk {
  hotspot_id: string;
  rain_rate: number;
  acc_1h: number;
  acc_3h: number;
  risk: number;
  level: Level;
  /** Highest level the nowcast expects within the hour, when, and the rain expected */
  fc_level: Level | null;
  fc_eta_min: number | null;
  fc_acc_1h: number | null;
}

export interface FloodRisk {
  time: string;
  hotspots: HotspotRisk[];
}

export interface Alert {
  time: string;
  hotspot_id: string;
  name: string;
  /** "forecast": early warning from the nowcast; "observed": the level was reached */
  kind: "forecast" | "observed";
  level: Level;
  eta_min: number | null;
  /** Forecast alerts: arrival range from the storm speed's uncertainty (null if no range) */
  eta_low_min: number | null;
  eta_high_min: number | null;
  /** observed: mm in the last hour; forecast: mm expected in the next hour */
  acc_1h: number;
  message: string;
}

export const LEADS = [0, 15, 30, 60] as const;
export type Lead = (typeof LEADS)[number];
