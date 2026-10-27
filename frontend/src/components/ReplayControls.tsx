interface Props {
  times: string[];
  index: number;
  onIndex: (index: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
}

export default function ReplayControls({ times, index, onIndex, playing, onPlaying }: Props) {
  const atEnd = index >= times.length - 1;
  return (
    <div className="flex items-center gap-3 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-3">
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
        className="flex-1 accent-[#2a78d6]"
        aria-label="Time"
      />
      <span className="tabular w-40 text-right text-sm text-[var(--ink-2)]">
        {times[index]?.replace("T", " ").slice(0, 16)}
      </span>
    </div>
  );
}
