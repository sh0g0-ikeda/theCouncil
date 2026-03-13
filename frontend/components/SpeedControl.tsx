"use client";

const MODES = ["normal", "fast", "instant", "paused"] as const;

export function SpeedControl({
  value,
  onChange
}: {
  value: string;
  onChange: (mode: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          onClick={() => onChange(mode)}
          className={`rounded border px-3 py-1 text-xs font-semibold uppercase tracking-wide transition ${
            value === mode
              ? "border-board-accent bg-board-accent text-white"
              : "border-board-border bg-board-paper text-board-ink hover:bg-white"
          }`}
        >
          {mode}
        </button>
      ))}
    </div>
  );
}

