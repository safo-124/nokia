import { useEffect, useMemo, useRef, useState } from "react";

import { LANGUAGES, SENDER, smsSize, smsText, type Language } from "../sms";
import type { Alert, Hotspots } from "../types";

interface Props {
  alerts: Alert[];
  hotspots: Hotspots;
  hotspotId: string;
  onHotspot: (id: string) => void;
  currentTime: string;
  lang: Language;
  onLang: (lang: Language) => void;
}

const alertKey = (a: Alert) => `${a.hotspot_id}-${a.kind}-${a.level}-${a.time}`;
const minutesBetween = (from: string, to: string) => (Date.parse(to) - Date.parse(from)) / 60000;

function SignalIcon() {
  return (
    <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={i * 4.5} y={7 - i * 2.3} width="3" height={3 + i * 2.3} rx="0.8" fill="currentColor" />
      ))}
    </svg>
  );
}

function smsCount(alerts: Alert[], lang: Language) {
  return alerts.reduce((n, a) => n + smsSize(smsText(a, lang)).parts, 0);
}

export default function PhoneMockup({ alerts, hotspots, hotspotId, onHotspot, currentTime, lang, onLang }: Props) {
  const inbox = useMemo(
    () => alerts.filter((a) => a.hotspot_id === hotspotId && a.time <= currentTime),
    [alerts, hotspotId, currentTime],
  );
  const latest = inbox.at(-1);
  const latestKey = latest ? alertKey(latest) : null;

  // Keep the newest message in view
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [latestKey, lang]);

  // A lock-screen style banner when a message arrives during the replay, not when
  // switching resident or dragging the slider far ahead
  const [banner, setBanner] = useState<Alert | null>(null);
  const shown = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    const isNew = latest && shown.current !== null && latestKey !== shown.current;
    shown.current = latestKey;
    if (isNew && minutesBetween(latest.time, currentTime) <= 2) {
      setBanner(latest);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setBanner(null), 3500);
    }
  }, [latestKey, latest, currentTime]);
  useEffect(() => {
    setBanner(null);
    shown.current = null;
  }, [hotspotId]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const name = hotspots.features.find((f) => f.properties.id === hotspotId)?.properties.name ?? hotspotId;
  const byName = useMemo(
    () => [...hotspots.features].sort((a, b) => a.properties.name.localeCompare(b.properties.name)),
    [hotspots],
  );
  const sms = { en: smsCount(inbox, "en"), tw: smsCount(inbox, "tw") };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <label className="flex items-center gap-1.5 text-[var(--ink-2)]">
          Resident in
          <select
            value={hotspotId}
            onChange={(e) => onHotspot(e.target.value)}
            className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-1.5 py-1 text-[var(--ink)]"
          >
            {byName.map((f) => (
              <option key={f.properties.id} value={f.properties.id}>
                {f.properties.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-1" role="group" aria-label="SMS language">
          {(Object.keys(LANGUAGES) as Language[]).map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={lang === l}
              onClick={() => onLang(l)}
              className={`rounded-md border px-2 py-1 ${
                lang === l
                  ? "border-[#2a78d6] bg-[#2a78d6] text-white"
                  : "border-[var(--border)] text-[var(--ink-2)] hover:bg-[var(--page)]"
              }`}
            >
              {LANGUAGES[l]}
            </button>
          ))}
        </div>
      </div>

      {/* Phone frame */}
      <div className="mx-auto w-[272px] rounded-[2.4rem] bg-[#111] p-2.5 shadow-lg ring-1 ring-black/40">
        <div className="relative flex h-[500px] flex-col overflow-hidden rounded-[1.9rem] bg-[var(--phone-screen)] text-[var(--ink)]">
          <div className="flex items-center justify-between px-5 pb-1 pt-2.5 text-[11px] font-semibold">
            <span className="tabular">{currentTime.slice(11, 16)}</span>
            <span className="absolute left-1/2 top-2 h-5 w-20 -translate-x-1/2 rounded-full bg-[#111]" aria-hidden />
            <span className="flex items-center gap-1">
              <SignalIcon /> 4G
            </span>
          </div>

          {banner && (
            <div className="sms-banner absolute inset-x-2 top-9 z-10 rounded-2xl bg-[var(--surface)] p-2.5 text-xs shadow-lg ring-1 ring-[var(--border)]">
              <div className="flex justify-between font-semibold">
                <span>{SENDER}</span>
                <span className="font-normal text-[var(--muted)]">now</span>
              </div>
              <p className="mt-0.5 line-clamp-2">{smsText(banner, lang)}</p>
            </div>
          )}

          <div className="flex flex-col items-center border-b border-[var(--border)] pb-2 pt-1">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#2a78d6] text-[11px] font-bold text-white">
              S2R
            </div>
            <div className="mt-0.5 text-xs font-semibold">{SENDER}</div>
          </div>

          <div ref={scroller} className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
            {inbox.length === 0 ? (
              <p className="mt-16 text-center text-xs text-[var(--muted)]">
                No messages yet for {name}. Press play to replay the storm.
              </p>
            ) : (
              inbox.map((a) => {
                const text = smsText(a, lang);
                const size = smsSize(text);
                return (
                  <div key={alertKey(a)} className="sms-in max-w-[88%]">
                    <div className="rounded-2xl rounded-bl-md bg-[var(--bubble)] px-3 py-2 text-[13px] leading-snug">
                      {text}
                    </div>
                    <div className="tabular mt-0.5 pl-1 text-[10px] text-[var(--muted)]">
                      {a.time.slice(11, 16)} · {size.parts} SMS{size.encoding === "UCS-2" ? " (Unicode)" : ""}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="px-3 pb-4 pt-1">
            <div className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)]">
              Text message
            </div>
          </div>
        </div>
      </div>

      {inbox.length > 0 && (
        <p className="tabular mt-3 text-xs text-[var(--ink-2)]">
          {inbox.length} alerts so far = {sms.en} SMS in English, {sms.tw} in Twi. Twi letters such as ɛ and ɔ are
          outside the basic SMS alphabet, so each Twi SMS holds 70 characters instead of 160.
        </p>
      )}
    </div>
  );
}
