import { LEADS, type Lead } from "../types";

interface Props {
  times: string[];
  index: number;
  onIndex: (index: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
  lead: Lead;
  onLead: (lead: Lead) => void;
}

export default function ReplayControls({ times, index, onIndex, playing, onPlaying, lead, onLead }: Props) {
  const atEnd = index >= times.length - 1;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <button
        type="button"
        onClick={() => {
          if (atEnd) onIndex(0);
          onPlaying(!playing);
        }}
        className="w-24 rounded-md bg-[#2a78d6] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#256abf]"
      >
        {playing ? "Pause" : atEnd ? "Replay" : "Play storm"}
      </button>
      <input
        type="range"
        min={0}
        max={times.length - 1}
        value={index}
        onChange={(e) => {
          onPlaying(false);
          onIndex(Number(e.target.value));
        }}
        className="min-w-40 flex-1 accent-[#2a78d6]"
        aria-label="Time"
      />
      <span className="tabular w-32 text-right text-sm text-[var(--ink-2)]">
        {times[index]?.replace("T", " ").slice(0, 16)}
      </span>
      <div className="flex items-center gap-1 text-sm" role="group" aria-label="Map shows">
        <span className="mr-1 text-[var(--muted)]">Map</span>
        {LEADS.map((l) => (
          <button
            key={l}
            type="button"
            aria-pressed={lead === l}
            onClick={() => onLead(l)}
            className={`rounded-md border px-2 py-1 ${
              lead === l
                ? "border-[#2a78d6] bg-[#2a78d6] text-white"
                : "border-[var(--border)] text-[var(--ink-2)] hover:bg-[var(--page)]"
            }`}
          >
            {l === 0 ? "Now" : `+${l} min`}
          </button>
        ))}
      </div>
    </div>
  );
}
