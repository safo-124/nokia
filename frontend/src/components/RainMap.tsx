import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import { Fragment, useEffect, useMemo } from "react";
import {
  CircleMarker,
  ImageOverlay,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";

import { hexToRgb, LEVEL_RANK, RAIN_STEPS, rainColor, RISK, SERIES } from "../colors";
import type { FloodRisk, Gauges, GridFrame, HotspotRisk, Hotspots, LinkRain, Links, Meta } from "../types";

// Standard OSM tiles are fine for a demo; see their usage policy before production.
// Dark mode inverts them with a CSS filter (.tiles-dark in index.css).
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(bounds, { padding: [16, 16] });
  }, [map, bounds]);
  return null;
}

// Draw the rain grid into a tiny image, one pixel per cell, and let the browser
// scale it up smoothly. Grid rows run south to north, image rows north to south.
function gridImage(frame: GridFrame): string {
  const ny = frame.lat.length;
  const nx = frame.lon.length;
  const canvas = document.createElement("canvas");
  canvas.width = nx;
  canvas.height = ny;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(nx, ny);
  for (let j = 0; j < ny; j++) {
    const row = frame.rain_rate[ny - 1 - j];
    for (let i = 0; i < nx; i++) {
      const color = rainColor(row[i]);
      if (!color) continue;
      const k = 4 * (j * nx + i);
      [img.data[k], img.data[k + 1], img.data[k + 2]] = hexToRgb(color);
      img.data[k + 3] = 210;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL();
}

function gridBounds({ lat, lon }: GridFrame): LatLngBoundsExpression {
  const dLat = (lat[1] - lat[0]) / 2;
  const dLon = (lon[1] - lon[0]) / 2;
  return [
    [lat[0] - dLat, lon[0] - dLon],
    [lat[lat.length - 1] + dLat, lon[lon.length - 1] + dLon],
  ];
}

const toLatLng = ([lon, lat]: number[]): LatLngTuple => [lat, lon];

function fmt(rate: number | null | undefined): string {
  return rate == null ? "no data" : `${rate.toFixed(1)} mm/h`;
}

const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];

function StormBadge({ grid }: { grid: GridFrame }) {
  const { speed_kmh, bearing_deg, speed_sd_kmh } = grid.motion;
  const plusMinus = speed_sd_kmh != null ? ` ± ${speed_sd_kmh.toFixed(0)}` : "";
  const moving = speed_kmh >= 1;
  return (
    <div className="absolute right-3 top-3 z-[1000] max-w-56 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--ink-2)] shadow-sm">
      <div className="flex items-center gap-2 font-medium text-[var(--ink)]">
        {moving && (
          <svg width="16" height="16" viewBox="0 0 16 16" style={{ transform: `rotate(${bearing_deg}deg)` }} aria-hidden>
            <path d="M8 1 L13 9 H9.5 V15 H6.5 V9 H3 Z" fill="currentColor" />
          </svg>
        )}
        {moving
          ? `Storm moving ${COMPASS[Math.round(bearing_deg / 45) % 8]} at ${speed_kmh.toFixed(0)}${plusMinus} km/h`
          : "No clear storm motion"}
      </div>
      {grid.lead_min > 0 && (
        <div className="mt-1">
          Nowcast for {grid.valid_time.slice(11, 16)} (+{grid.lead_min} min). Rain moves with the storm; areas
          without a source upwind stay blank.
        </div>
      )}
    </div>
  );
}

function LineSwatch({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg width="22" height="6" aria-hidden>
      <line x1="1" y1="3" x2="21" y2="3" stroke={color} strokeWidth="2.5" strokeDasharray={dashed ? "4 4" : undefined} />
    </svg>
  );
}

function Legend({ showRisk, showExcluded, lineColor }: { showRisk: boolean; showExcluded: boolean; lineColor: string }) {
  return (
    <div className="absolute bottom-6 left-3 z-[1000] rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--ink-2)] shadow-sm">
      <div className="mb-1 font-medium text-[var(--ink)]">Rain rate (mm/h)</div>
      <div className="flex">
        {RAIN_STEPS.map(([bound, color]) => (
          <div key={bound} className="flex w-8 flex-col items-center">
            <div className="h-3 w-full" style={{ background: color }} />
            <span className="tabular mt-0.5">{bound}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-3">
        <span className="flex items-center gap-1">
          <LineSwatch color={lineColor} /> Dry link
        </span>
        {showExcluded && (
          <span className="flex items-center gap-1">
            <LineSwatch color={lineColor} dashed /> Left out (quality)
          </span>
        )}
      </div>
      {showRisk && (
        <div className="mt-2 flex gap-3">
          {Object.entries(RISK).map(([level, { color, label }]) => (
            <span key={level} className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
              {label} risk
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

interface Props {
  meta: Meta;
  links: Links | null;
  linkRain?: LinkRain;
  grid?: GridFrame;
  gauges: Gauges | null;
  hotspots: Hotspots | null;
  risk?: FloodRisk | null;
  selectedGauge: string | null;
  onSelectGauge: (id: string) => void;
  selectedHotspot: string | null;
  onSelectHotspot: (id: string) => void;
  dark: boolean;
}

export default function RainMap({
  meta,
  links,
  linkRain,
  grid,
  gauges,
  hotspots,
  risk,
  selectedGauge,
  onSelectGauge,
  selectedHotspot,
  onSelectHotspot,
  dark,
}: Props) {
  const bounds = useMemo<LatLngBoundsExpression>(
    () => [
      [meta.bounds[0], meta.bounds[2]],
      [meta.bounds[1], meta.bounds[3]],
    ],
    [meta],
  );
  const image = useMemo(() => grid && gridImage(grid), [grid]);
  const imageBounds = useMemo(() => grid && gridBounds(grid), [grid]);
  const riskById = useMemo<Record<string, HotspotRisk>>(
    () => Object.fromEntries((risk?.hotspots ?? []).map((h) => [h.hotspot_id, h])),
    [risk],
  );
  const series = SERIES[dark ? "dark" : "light"];
  // Excluded links first, so working links draw on top of them
  const sortedLinks = useMemo(
    () => [...(links?.features ?? [])].sort((a, b) => Number(b.properties.excluded) - Number(a.properties.excluded)),
    [links],
  );

  return (
    <div className="relative h-full w-full">
      <MapContainer className="h-full w-full" center={[0, 0]} zoom={11} preferCanvas>
        <FitBounds bounds={bounds} />
        <TileLayer
          key={dark ? "dark" : "light"}
          url={TILES}
          attribution={ATTRIBUTION}
          className={dark ? "tiles-dark" : "tiles-light"}
          // CORS requests, so the tile-cache service worker can store real (not opaque) responses
          crossOrigin="anonymous"
        />
        {image && imageBounds && <ImageOverlay url={image} bounds={imageBounds} opacity={0.8} />}

        {/* A casing under each link keeps it visible on top of the rain overlay */}
        {links?.features.map((f) => (
          <Polyline
            key={`casing-${f.properties.id}`}
            positions={f.geometry.coordinates.map(toLatLng)}
            pathOptions={{ color: series.surface, weight: 5, opacity: 0.9, interactive: false }}
          />
        ))}
        {sortedLinks.map((f) => {
          const { id, frequency_ghz, length_km, excluded, exclude_reason } = f.properties;
          const rate = linkRain?.rain_rate[id];
          return (
            <Polyline
              key={id}
              positions={f.geometry.coordinates.map(toLatLng)}
              pathOptions={
                excluded
                  ? { color: series.axis, weight: 2, opacity: 0.9, dashArray: "4 4" }
                  : { color: rainColor(rate) ?? series.axis, weight: 2.5, opacity: 1 }
              }
            >
              <Tooltip sticky>
                <strong>Link {id}</strong> · {frequency_ghz} GHz · {length_km} km
                <br />
                {excluded ? `Left out of the map: ${exclude_reason}` : fmt(rate)}
              </Tooltip>
            </Polyline>
          );
        })}

        {gauges?.features.map((f) => {
          const { id } = f.properties;
          const selected = id === selectedGauge;
          return (
            <CircleMarker
              key={id}
              center={toLatLng(f.geometry.coordinates)}
              radius={selected ? 8 : 6}
              pathOptions={{
                color: selected ? series.gauge : "#52514e",
                weight: selected ? 3 : 1.5,
                fillColor: "#fcfcfb",
                fillOpacity: 1,
              }}
              eventHandlers={{ click: () => onSelectGauge(id) }}
            >
              <Tooltip>Rain gauge {id} (click to compare)</Tooltip>
            </CircleMarker>
          );
        })}

        {hotspots?.features.map((f) => {
          const { id, name } = f.properties;
          const r = riskById[id];
          const level = RISK[r?.level ?? "low"];
          // A dashed ring in the forecast colour when the nowcast expects worse within the hour
          const rising = r?.fc_level && LEVEL_RANK[r.fc_level] > LEVEL_RANK[r.level] ? r.fc_level : null;
          const center = toLatLng(f.geometry.coordinates);
          return (
            <Fragment key={id}>
              {rising && (
                <CircleMarker
                  center={center}
                  radius={15}
                  pathOptions={{ color: RISK[rising].color, weight: 3, dashArray: "5 4", fill: false, interactive: false }}
                />
              )}
              <CircleMarker
                center={center}
                radius={id === selectedHotspot ? 11 : 9}
                pathOptions={{
                  color: id === selectedHotspot ? "#2a78d6" : "#0b0b0b",
                  weight: id === selectedHotspot ? 3 : 1,
                  fillColor: level.color,
                  fillOpacity: 0.95,
                }}
                eventHandlers={{ click: () => onSelectHotspot(id) }}
              >
                <Tooltip>
                  <strong>{name}</strong> · {level.label} flood risk now (click for a resident's phone)
                  {r && (
                    <>
                      <br />
                      {r.acc_1h.toFixed(0)} mm last hour, {r.acc_3h.toFixed(0)} mm last 3 hours
                    </>
                  )}
                  {rising && r && (
                    <>
                      <br />
                      <strong>Expected: {RISK[rising].label} in about {r.fc_eta_min} min</strong> (
                      {r.fc_acc_1h?.toFixed(0)} mm forecast next hour)
                    </>
                  )}
                </Tooltip>
              </CircleMarker>
            </Fragment>
          );
        })}
      </MapContainer>
      {grid && <StormBadge grid={grid} />}
      <Legend
        showRisk={Boolean(hotspots)}
        showExcluded={sortedLinks.some((f) => f.properties.excluded)}
        lineColor={series.axis}
      />
    </div>
  );
}
