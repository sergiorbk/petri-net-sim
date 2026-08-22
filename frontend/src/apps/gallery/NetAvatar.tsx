import { memo, useMemo } from "react";
import { cn } from "@/lib/utils";

const GRID = 5;
/** Columns actually generated — the rest of each row mirrors these around the center column, the classic identicon symmetry. */
const HALF = Math.ceil(GRID / 2);
const CELL = 100 / GRID;

/** FNV-1a — small, deterministic, good enough bit-spread for a visual seed, not cryptography. */
function hashSeed(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32 — a tiny PRNG, seeded once from the hash so the whole grid (and nothing else) depends only on `seed`. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Identicon {
  /** [row][col], already mirrored to the full GRID width. */
  cells: boolean[][];
  hue: number;
}

function buildIdenticon(seed: string): Identicon {
  const rand = mulberry32(hashSeed(seed));
  const cells: boolean[][] = [];
  for (let row = 0; row < GRID; row++) {
    const half: boolean[] = [];
    for (let col = 0; col < HALF; col++) half.push(rand() > 0.55);
    const mirror = half.slice(0, GRID - HALF).reverse();
    cells.push([...half, ...mirror]);
  }
  // A fresh draw for hue so it doesn't correlate with which cells happen to be filled.
  const hue = Math.floor(rand() * 360);
  return { cells, hue };
}

interface Props {
  /** Stable identity to derive the pattern from — a net's id, so the picture never changes as it's renamed. */
  seed: string;
  className?: string;
}

/**
 * A GitHub-style default avatar: a deterministic, symmetric pixel pattern in
 * a hue derived from `seed`. No net content is read to draw this — same seed,
 * same picture, every time, with nothing to keep in sync as the net changes.
 */
export const NetAvatar = memo(function NetAvatar({ seed, className }: Props) {
  const { cells, hue } = useMemo(() => buildIdenticon(seed), [seed]);
  const fill = `hsl(${hue} 62% 52%)`;

  return (
    <svg viewBox="0 0 100 100" className={cn(className)} aria-hidden="true">
      {cells.map((row, r) =>
        row.map(
          (on, c) =>
            on && (
              <rect
                key={`${r}-${c}`}
                x={c * CELL}
                y={r * CELL}
                width={CELL}
                height={CELL}
                fill={fill}
              />
            ),
        ),
      )}
    </svg>
  );
});
