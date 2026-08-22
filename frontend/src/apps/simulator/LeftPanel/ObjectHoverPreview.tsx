import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import type { PetriObjectDetail } from "@/lib/petri-objects-client";

const PREVIEW_W = 240;
const PREVIEW_H = 180;

const PLACE_R = 16;
const TRANS_W = 10;
const TRANS_H = 24;

export function ObjectHoverPreview({
  detail,
  anchor,
}: {
  detail: PetriObjectDetail;
  anchor: { x: number; y: number };
}) {
  const { template_data: t } = detail;
  if (t.places.length === 0 && t.transitions.length === 0) return null;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  for (const p of t.places) {
    minX = Math.min(minX, p.graphics.x);
    minY = Math.min(minY, p.graphics.y);
    maxX = Math.max(maxX, p.graphics.x);
    maxY = Math.max(maxY, p.graphics.y);
  }
  for (const tr of t.transitions) {
    minX = Math.min(minX, tr.graphics.x);
    minY = Math.min(minY, tr.graphics.y);
    maxX = Math.max(maxX, tr.graphics.x);
    maxY = Math.max(maxY, tr.graphics.y);
  }

  const rawW = maxX - minX || 1;
  const rawH = maxY - minY || 1;
  const pad = 40;
  const scaleX = (PREVIEW_W - pad * 2) / rawW;
  const scaleY = (PREVIEW_H - pad * 2) / rawH;
  const scale = Math.min(scaleX, scaleY, 2);

  function tx(x: number) {
    return pad + (x - minX) * scale;
  }
  function ty(y: number) {
    return pad + (y - minY) * scale;
  }

  const posMap = new Map<string, { cx: number; cy: number }>();
  for (const p of t.places) {
    posMap.set(p.id, { cx: tx(p.graphics.x), cy: ty(p.graphics.y) });
  }
  for (const tr of t.transitions) {
    posMap.set(tr.id, { cx: tx(tr.graphics.x), cy: ty(tr.graphics.y) });
  }

  const top = Math.max(8, anchor.y);

  return createPortal(
    <div
      style={{ left: anchor.x, top }}
      className={cn(
        "pointer-events-none fixed z-[100]",
        "rounded-lg border border-border bg-surface p-2 shadow-xl",
      )}
    >
      <p className="mb-1 text-[11px] font-semibold text-text-primary">
        {detail.name}
      </p>
      {detail.description && (
        <p className="mb-1 text-[10px] text-text-muted line-clamp-2">
          {detail.description}
        </p>
      )}
      <svg
        width={PREVIEW_W}
        height={PREVIEW_H}
        className="rounded bg-zinc-50 dark:bg-zinc-900"
      >
        {t.arcs.map((a) => {
          const s = posMap.get(a.source_id);
          const e = posMap.get(a.target_id);
          if (!s || !e) return null;
          return (
            <line
              key={a.id}
              x1={s.cx}
              y1={s.cy}
              x2={e.cx}
              y2={e.cy}
              stroke="#6b7280"
              strokeWidth={1.2}
              markerEnd="url(#arrowhead)"
            />
          );
        })}

        {t.places.map((p) => {
          const pos = posMap.get(p.id)!;
          return (
            <g key={p.id}>
              <circle
                cx={pos.cx}
                cy={pos.cy}
                r={PLACE_R * Math.min(scale, 1)}
                fill="white"
                stroke="#3b82f6"
                strokeWidth={1.5}
              />
              {p.tokens > 0 && (
                <text
                  x={pos.cx}
                  y={pos.cy + 3}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#1e40af"
                >
                  {p.tokens}
                </text>
              )}
            </g>
          );
        })}

        {t.transitions.map((tr) => {
          const pos = posMap.get(tr.id)!;
          const hw = (TRANS_W * Math.min(scale, 1)) / 2;
          const hh = (TRANS_H * Math.min(scale, 1)) / 2;
          return (
            <rect
              key={tr.id}
              x={pos.cx - hw}
              y={pos.cy - hh}
              width={hw * 2}
              height={hh * 2}
              fill="#1e293b"
              rx={2}
            />
          );
        })}

        <defs>
          <marker
            id="arrowhead"
            markerWidth="8"
            markerHeight="6"
            refX="8"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 8 3, 0 6" fill="#6b7280" />
          </marker>
        </defs>
      </svg>
      <p className="mt-1 text-[10px] text-text-muted">
        {t.places.length}P / {t.transitions.length}T / {t.arcs.length}A
      </p>
    </div>,
    document.body,
  );
}
