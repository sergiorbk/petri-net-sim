import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type InputHTMLAttributes,
} from "react";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { cn } from "@/lib/utils";
import { Input } from "@/components/common/Input";
import { useEditorStore, EDGE_STYLE_OPTIONS, FRAME_STYLE_OPTIONS } from "@/stores/editor-store";
import { isLocalToNet, ownerOf } from "@/lib/petri-object-model";
import type {
  ArcType,
  DistributionType,
  ObjectFrame,
  ObjectLink,
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";

type DistributionChoice = DistributionType | "immediate";

const DISTRIBUTION_VALUES: readonly DistributionChoice[] = [
  "immediate",
  "exp",
  "norm",
  "unif",
  "det",
];

const ARC_TYPE_VALUES: readonly ArcType[] = ["NORMAL", "INHIBITOR", "READ"];

/**
 * A property field that reports its value on blur — and also when it goes
 * away. Collapsing the panel, clearing the selection, switching canvases and
 * deleting the element all unmount the field while it still holds focus, and
 * React fires no blur for a node it is removing, so an edit typed just before
 * would be silently dropped. Only a field the user actually typed in is
 * flushed, so unmounting an untouched field changes nothing.
 */
function CommitField({
  onBlur,
  onChange,
  ...inputProps
}: Omit<InputHTMLAttributes<HTMLInputElement>, "onBlur"> & {
  onBlur?: (event: { target: { value: string } }) => void;
}) {
  // The pending value is kept here rather than read back from the input on
  // flush: by the time an unmount cleanup runs, React has already detached the
  // DOM ref, so there would be nothing left to read.
  const pending = useRef<string | null>(null);
  const onBlurRef = useRef(onBlur);
  onBlurRef.current = onBlur;

  const flush = useCallback(() => {
    const value = pending.current;
    if (value === null) return;
    pending.current = null;
    onBlurRef.current?.({ target: { value } });
  }, []);

  useEffect(() => flush, [flush]);

  return (
    <Input
      onBlur={flush}
      onChange={(event) => {
        pending.current = event.target.value;
        onChange?.(event);
      }}
      {...inputProps}
    />
  );
}

export function PropertyInspector({ readOnly = false }: { readOnly?: boolean }) {
  const { t } = useTranslation();
  const net = useEditorStore((s) => s.net);
  const selection = useEditorStore((s) => s.selection);
  const [collapsed, setCollapsed] = useState(true);
  const collapseSignal = useEditorStore((s) => s.inspectorCollapseSignal);

  useEffect(() => {
    if (selection.length > 0) setCollapsed(false);
  }, [selection]);

  useEffect(() => {
    if (collapseSignal > 0) setCollapsed(true);
  }, [collapseSignal]);

  const primary = selection[0] ?? null;
  const isMulti = selection.length > 1;

  // A place/transition/object visible here only because its actual owner is
  // expanded isn't editable from here, the same restriction the canvas
  // itself enforces (drag, delete, wiring) — this panel is the one other
  // place that edits those fields, so it needs the identical check. A link
  // crosses object boundaries by definition, so it's never "someone else's
  // internals"; a plain arc is local only when both its ends are, since it
  // always shares one owner by construction.
  const primaryIsLocal = useMemo(() => {
    if (!primary || primary.kind === "link") return true;
    if (primary.kind === "arc") {
      const arc = net.arcs.find((a) => a.id === primary.id);
      return !arc || ownerOf(net, arc.source_id) === undefined;
    }
    return isLocalToNet(net, primary.id);
  }, [primary, net]);
  const effectiveReadOnly = readOnly || !primaryIsLocal;

  const body = useMemo(() => {
    if (isMulti) {
      return <MultiSelectionView count={selection.length} />;
    }
    if (!primary) {
      return <NetView net={net} readOnly={effectiveReadOnly} />;
    }
    if (primary.kind === "place") {
      const place = net.places.find((p) => p.id === primary.id);
      return place ? <PlaceView place={place} readOnly={effectiveReadOnly} /> : <MissingView />;
    }
    if (primary.kind === "transition") {
      const trans = net.transitions.find((t) => t.id === primary.id);
      return trans ? (
        <TransitionView transition={trans} net={net} readOnly={effectiveReadOnly} />
      ) : (
        <MissingView />
      );
    }
    if (primary.kind === "object") {
      const frame = (net.objects ?? []).find((o) => o.id === primary.id);
      return frame ? <ObjectFrameView frame={frame} readOnly={effectiveReadOnly} /> : <MissingView />;
    }
    if (primary.kind === "link") {
      const link = (net.links ?? []).find((l) => l.id === primary.id);
      return link ? <ObjectLinkView link={link} net={net} readOnly={effectiveReadOnly} /> : <MissingView />;
    }
    const arc = net.arcs.find((a) => a.id === primary.id);
    return arc ? <ArcView arc={arc} net={net} readOnly={effectiveReadOnly} /> : <MissingView />;
  }, [isMulti, primary, selection.length, net, effectiveReadOnly]);

  if (collapsed) {
    return (
      <aside
        aria-label={t("inspector.properties")}
        className="flex h-full w-8 shrink-0 flex-col items-center border-l border-border bg-surface-secondary"
      >
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title={t("inspector.expandProperties")}
          className="flex h-8 w-8 items-center justify-center text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <ChevronLeft size={14} />
        </button>
        <span
          aria-hidden="true"
          className="mt-6 origin-center -rotate-90 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wide text-text-muted"
        >
          {t("inspector.properties")}
        </span>
      </aside>
    );
  }

  return (
    <aside
      aria-label={t("inspector.properties")}
      className={cn(
        "flex h-full w-72 shrink-0 flex-col border-l border-border",
        "bg-surface-secondary",
      )}
    >
      <header className="flex items-start justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{t("inspector.properties")}</h2>
          <p className="mt-0.5 text-xs text-text-muted">
            {headerSubtitle(t, isMulti, primary)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title={t("inspector.collapseProperties")}
          className="ml-2 mt-0.5 rounded p-0.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <ChevronRight size={14} />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{body}</div>
    </aside>
  );
}

function headerSubtitle(
  t: TFunction,
  isMulti: boolean,
  primary: { kind: string } | null,
): string {
  if (isMulti) return t("inspector.subtitle.multipleElements");
  if (!primary) return t("inspector.subtitle.netProperties");
  if (primary.kind === "place") return t("inspector.subtitle.place");
  if (primary.kind === "transition") return t("inspector.subtitle.transition");
  if (primary.kind === "object") return t("inspector.subtitle.object");
  if (primary.kind === "link") return t("inspector.subtitle.link");
  return t("inspector.subtitle.arc");
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5">
      <h3
        className={cn(
          "mb-2 text-[11px] font-semibold uppercase tracking-wide",
          "text-text-muted",
        )}
      >
        {title}
      </h3>
      <div className="flex flex-col gap-2.5">{children}</div>
    </section>
  );
}

function TooltipLines({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, i) => (
        <span
          key={i}
          className={cn(
            "block",
            line.startsWith("→") || line.startsWith("Напр") || line.startsWith("E.g") || line.startsWith("Note") || line.startsWith("Увага")
              ? "mt-0.5 pl-1 text-text-muted"
              : i > 0
                ? "mt-1.5"
                : "",
          )}
        >
          {line}
        </span>
      ))}
    </>
  );
}

function HelpTooltip({ textKey }: { textKey: string }) {
  const { t } = useTranslation();
  return (
    <>
      <span
        aria-hidden
        className={cn(
          "ml-auto flex h-3.5 w-3.5 shrink-0 cursor-default select-none",
          "items-center justify-center rounded-full border border-current",
          "text-[9px] font-bold text-text-muted transition-colors",
          "group-hover/field:border-text-primary group-hover/field:text-text-primary",
        )}
      >
        ?
      </span>
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-0 top-full z-50 mt-1 w-full",
          "invisible opacity-0",
          "transition-[opacity,visibility] duration-200 delay-0",
          "group-hover/field:visible group-hover/field:opacity-100 group-hover/field:delay-1000",
          "block rounded-lg border border-border bg-surface px-3 py-2.5 shadow-lg",
          "text-[11px] leading-relaxed text-text-secondary",
        )}
      >
        <TooltipLines text={t(textKey)} />
      </span>
    </>
  );
}

type DistTooltipState = { value: DistributionChoice; x: number; y: number } | null;

function DistributionSelect({
  value,
  onChange,
  readOnly,
}: {
  value: DistributionChoice;
  onChange: (v: DistributionChoice) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [tooltip, setTooltip] = useState<DistTooltipState>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      if (tooltipTimer.current) clearTimeout(tooltipTimer.current);
      setTooltip(null);
    }
  }, [open]);

  function handleBadgeEnter(optValue: DistributionChoice, e: React.MouseEvent<HTMLSpanElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    if (tooltipTimer.current) clearTimeout(tooltipTimer.current);
    tooltipTimer.current = setTimeout(() => {
      setTooltip({ value: optValue, x: rect.left - 8, y: rect.top });
    }, 1000);
  }

  function handleBadgeLeave() {
    if (tooltipTimer.current) clearTimeout(tooltipTimer.current);
    tooltipTimer.current = null;
    setTooltip(null);
  }

  const currentLabel = t(`inspector.distributions.${value}`);

  if (readOnly) {
    return (
      <div className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-muted">
        {currentLabel}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center justify-between rounded-lg border border-border",
          "bg-surface-secondary px-3 py-2 text-sm text-text-primary transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          open && "border-accent",
        )}
      >
        <span>{currentLabel}</span>
        <ChevronDown
          size={14}
          className={cn("text-text-muted transition-transform duration-150", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-lg border border-border bg-surface shadow-lg">
          {DISTRIBUTION_VALUES.map((optValue) => (
            <div key={optValue} className="flex items-stretch">
              <button
                type="button"
                onClick={() => { onChange(optValue); setOpen(false); }}
                className={cn(
                  "flex-1 px-3 py-2 text-left text-sm transition-colors hover:bg-surface-hover",
                  "first:rounded-t-lg last:rounded-b-lg",
                  optValue === value
                    ? "font-medium text-accent"
                    : "text-text-primary",
                )}
              >
                {t(`inspector.distributions.${optValue}`)}
              </button>
              <div className="flex items-center px-2">
                <span
                  aria-hidden
                  onMouseEnter={(e) => handleBadgeEnter(optValue, e)}
                  onMouseLeave={handleBadgeLeave}
                  className={cn(
                    "flex h-3.5 w-3.5 cursor-default select-none items-center justify-center",
                    "rounded-full border border-current text-[9px] font-bold",
                    "text-text-muted transition-colors hover:border-text-primary hover:text-text-primary",
                  )}
                >
                  ?
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {tooltip && (
        <div
          role="tooltip"
          className={cn(
            "pointer-events-none fixed z-[9999] w-52 -translate-x-full -translate-y-1/2",
            "rounded-lg border border-border bg-surface px-3 py-2.5 shadow-lg",
            "text-[11px] leading-relaxed text-text-secondary",
          )}
          style={{ left: tooltip.x, top: tooltip.y + 8 }}
        >
          <TooltipLines text={t(`inspector.hints.dist.${tooltip.value}`)} />
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
  help,
}: {
  label: string;
  children: React.ReactNode;
  help?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className={cn(
          "text-xs text-text-secondary",
          help && "group/field relative flex items-center gap-1",
        )}
      >
        {label}
        {help && <HelpTooltip textKey={help} />}
      </span>
      {children}
    </label>
  );
}

function ReadOnlyValue({ value }: { value: string }) {
  return (
    <div
      className={cn(
        "w-full rounded-lg border border-border bg-surface px-3 py-2",
        "text-sm text-text-muted",
      )}
    >
      {value}
    </div>
  );
}

type TimeUnit = "s" | "min" | "h";
const TIME_FACTORS: Record<TimeUnit, number> = { s: 1, min: 60, h: 3600 };

function inferUnit(secs: number): TimeUnit {
  if (secs > 0 && secs % 3600 === 0) return "h";
  if (secs > 0 && secs % 60 === 0) return "min";
  return "s";
}

function DelayInput({
  id,
  valueSecs,
  onChange,
  readOnly,
  min = 0,
}: {
  id: string;
  valueSecs: number;
  onChange: (secs: number) => void;
  readOnly: boolean;
  min?: number;
}) {
  const [unit, setUnit] = useState<TimeUnit>(() => inferUnit(valueSecs));
  const factor = TIME_FACTORS[unit];
  const displayVal = +(valueSecs / factor).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");

  if (readOnly) {
    return <ReadOnlyValue value={`${displayVal} ${unit}`} />;
  }

  return (
    <div className="flex gap-1.5">
      <CommitField
        key={`${id}-${unit}`}
        type="number"
        min={min / factor}
        step="any"
        defaultValue={displayVal}
        onBlur={(e) => {
          const next = parseFloat(e.target.value);
          if (!isNaN(next)) {
            const secs = Math.max(min, next * factor);
            if (secs !== valueSecs) onChange(secs);
          }
        }}
        className="min-w-0 flex-1"
      />
      <select
        value={unit}
        onChange={(e) => setUnit(e.target.value as TimeUnit)}
        className={cn(
          "w-[4.5rem] shrink-0 rounded-lg border border-border bg-surface-secondary",
          "px-2 py-2 text-sm text-text-primary transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        )}
      >
        <option value="s">s</option>
        <option value="min">min</option>
        <option value="h">h</option>
      </select>
    </div>
  );
}

function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (next: T) => void;
  options: readonly { value: T; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className={cn(
        "w-full rounded-lg border border-border bg-surface-secondary",
        "px-3 py-2 text-sm text-text-primary transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2",
        "focus-visible:outline-accent",
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function MissingView() {
  const { t } = useTranslation();
  return (
    <p className="text-sm text-text-muted">
      {t("inspector.missingElement")}
    </p>
  );
}

function MultiSelectionView({ count }: { count: number }) {
  const { t } = useTranslation();
  return (
    <p className="text-sm text-text-muted">
      {t("inspector.multiSelect", { count })}
    </p>
  );
}

function NetView({ net, readOnly }: { net: PetriNetData; readOnly: boolean }) {
  const { t } = useTranslation();
  const renameNet = useEditorStore((s) => s.renameNet);
  const edgeStyle = useEditorStore((s) => s.edgeStyle);
  const setEdgeStyle = useEditorStore((s) => s.setEdgeStyle);
  const edgeLabel = EDGE_STYLE_OPTIONS.find((o) => o.value === edgeStyle)?.label ?? edgeStyle;
  const frameStyle = useEditorStore((s) => s.frameStyle);
  const setFrameStyle = useEditorStore((s) => s.setFrameStyle);
  const frameLabel = FRAME_STYLE_OPTIONS.find((o) => o.value === frameStyle)?.label ?? frameStyle;
  return (
    <Section title={t("inspector.section.net")}>
      <Field label={t("inspector.field.name")}>
        {readOnly ? (
          <ReadOnlyValue value={net.name} />
        ) : (
          <CommitField
            // Uncontrolled, so it has to be remounted when the name changes
            // from outside — switching canvases swaps the whole net underneath.
            key={net.name}
            defaultValue={net.name}
            onBlur={(e) => {
              const next = e.target.value.trim();
              if (next && next !== net.name) renameNet(next);
            }}
          />
        )}
      </Field>
      <Field label={t("inspector.field.counts")}>
        <ReadOnlyValue
          value={t("inspector.field.countsValue", {
            places: net.places.length,
            transitions: net.transitions.length,
            arcs: net.arcs.length,
          })}
        />
      </Field>
      <Field label={t("inspector.field.arcStyle")}>
        {readOnly ? (
          <ReadOnlyValue value={edgeLabel} />
        ) : (
          <Select value={edgeStyle} onChange={setEdgeStyle} options={EDGE_STYLE_OPTIONS} />
        )}
      </Field>
      <Field label={t("inspector.field.frameStyle")}>
        {readOnly ? (
          <ReadOnlyValue value={frameLabel} />
        ) : (
          <Select value={frameStyle} onChange={setFrameStyle} options={FRAME_STYLE_OPTIONS} />
        )}
      </Field>
    </Section>
  );
}

function PlaceView({ place, readOnly }: { place: PetriPlace; readOnly: boolean }) {
  const { t } = useTranslation();
  const updatePlace = useEditorStore((s) => s.updatePlace);
  return (
    <>
      <Section title={t("inspector.section.identification")}>
        <Field label={t("inspector.field.id")}>
          <ReadOnlyValue value={place.id} />
        </Field>
        <Field label={t("inspector.field.name")}>
          {readOnly ? (
            <ReadOnlyValue value={place.name} />
          ) : (
            <CommitField
              key={`name-${place.id}`}
              defaultValue={place.name}
              onBlur={(e) => {
                const next = e.target.value.trim();
                if (next && next !== place.name) updatePlace(place.id, { name: next });
              }}
            />
          )}
        </Field>
      </Section>
      <Section title={t("inspector.section.marking")}>
        <Field label={t("inspector.field.initialTokens")}>
          {readOnly ? (
            <ReadOnlyValue value={String(place.tokens)} />
          ) : (
            <CommitField
              key={`tokens-${place.id}`}
              type="number"
              min={0}
              step={1}
              defaultValue={place.tokens}
              onBlur={(e) => {
                const next = clampInt(e.target.value, 0);
                if (next !== place.tokens) updatePlace(place.id, { tokens: next });
              }}
            />
          )}
        </Field>
      </Section>
      <Section title={t("inspector.section.position")}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="x">
            {readOnly ? (
              <ReadOnlyValue value={String(place.graphics.x)} />
            ) : (
              <CommitField
                key={`x-${place.id}-${place.graphics.x}`}
                type="number"
                step={1}
                defaultValue={place.graphics.x}
                onBlur={(e) => {
                  const next = Number.parseFloat(e.target.value);
                  if (Number.isFinite(next) && next !== place.graphics.x) {
                    updatePlace(place.id, { graphics: { x: next, y: place.graphics.y } });
                  }
                }}
              />
            )}
          </Field>
          <Field label="y">
            {readOnly ? (
              <ReadOnlyValue value={String(place.graphics.y)} />
            ) : (
              <CommitField
                key={`y-${place.id}-${place.graphics.y}`}
                type="number"
                step={1}
                defaultValue={place.graphics.y}
                onBlur={(e) => {
                  const next = Number.parseFloat(e.target.value);
                  if (Number.isFinite(next) && next !== place.graphics.y) {
                    updatePlace(place.id, { graphics: { x: place.graphics.x, y: next } });
                  }
                }}
              />
            )}
          </Field>
        </div>
      </Section>
    </>
  );
}

function TransitionView({
  transition,
  net,
  readOnly,
}: {
  transition: PetriTransition;
  net: PetriNetData;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const updateTransition = useEditorStore((s) => s.updateTransition);

  const isImmediate = transition.distribution === null;
  const distChoice: DistributionChoice = isImmediate ? "immediate" : transition.distribution!;

  function handleDistributionChange(value: DistributionChoice) {
    if (value === "immediate") {
      updateTransition(transition.id, { distribution: null, mean_delay: 0 });
    } else {
      updateTransition(transition.id, { distribution: value });
    }
  }

  const conflictGroups = useMemo(() => {
    const inputPlaceIds = net.arcs
      .filter((a) => a.target_id === transition.id)
      .map((a) => a.source_id);
    return inputPlaceIds.flatMap((placeId) => {
      const place = net.places.find((p) => p.id === placeId);
      if (!place) return [];
      const siblings = net.transitions.filter(
        (t) =>
          t.id !== transition.id &&
          t.priority === transition.priority &&
          net.arcs.some((a) => a.source_id === placeId && a.target_id === t.id),
      );
      return siblings.length > 0 ? [{ place, siblings }] : [];
    });
  }, [transition.id, net]);

  const maxPct = useMemo(() => {
    if (conflictGroups.length === 0) return 100;
    let min = 100;
    for (const { siblings } of conflictGroups) {
      const sumSiblingsPct = siblings.reduce(
        (acc, t) => acc + (t.probability != null ? Math.round(t.probability * 100) : 0),
        0,
      );
      min = Math.min(min, 100 - sumSiblingsPct);
    }
    return Math.max(0, min);
  }, [conflictGroups]);

  const groupInfos = useMemo(
    () =>
      conflictGroups.map(({ place, siblings }) => {
        const selfPct = transition.probability != null ? Math.round(transition.probability * 100) : 0;
        const siblingExplicitPct = siblings.reduce(
          (acc, t) => acc + (t.probability != null ? Math.round(t.probability * 100) : 0),
          0,
        );
        const totalExplicitPct = selfPct + siblingExplicitPct;
        const remainingPct = 100 - totalExplicitPct;
        const countUnset = siblings.filter((t) => t.probability == null).length;
        const eachUnsetPct = countUnset > 0 ? Math.round(remainingPct / countUnset) : 0;
        return { place, totalExplicitPct, remainingPct, countUnset, eachUnsetPct };
      }),
    [conflictGroups, transition.probability],
  );

  const probPct = transition.probability != null ? Math.round(transition.probability * 100) : null;

  return (
    <>
      <Section title={t("inspector.section.identification")}>
        <Field label={t("inspector.field.id")}>
          <ReadOnlyValue value={transition.id} />
        </Field>
        <Field label={t("inspector.field.name")}>
          {readOnly ? (
            <ReadOnlyValue value={transition.name} />
          ) : (
            <CommitField
              key={`name-${transition.id}`}
              defaultValue={transition.name}
              onBlur={(e) => {
                const next = e.target.value.trim();
                if (next && next !== transition.name) updateTransition(transition.id, { name: next });
              }}
            />
          )}
        </Field>
      </Section>
      <Section title={t("inspector.section.firing")}>
        <Field label={t("inspector.field.priority")} help="inspector.hints.priority">
          {readOnly ? (
            <ReadOnlyValue value={String(transition.priority)} />
          ) : (
            <CommitField
              key={`priority-${transition.id}`}
              type="number"
              min={1}
              step={1}
              defaultValue={transition.priority}
              onBlur={(e) => {
                const next = clampInt(e.target.value, 1);
                if (next !== transition.priority) updateTransition(transition.id, { priority: next });
              }}
            />
          )}
        </Field>
        <Field label={t("inspector.field.distribution")}>
          <DistributionSelect
            value={distChoice}
            onChange={handleDistributionChange}
            readOnly={readOnly}
          />
        </Field>
        {!isImmediate && (
          <>
            <Field label={t("inspector.field.meanDelay")} help="inspector.hints.meanDelay">
              <DelayInput
                id={`mean-${transition.id}`}
                valueSecs={transition.mean_delay}
                onChange={(secs) => updateTransition(transition.id, { mean_delay: secs })}
                readOnly={readOnly}
                min={0.001}
              />
            </Field>
            {(distChoice === "norm" || distChoice === "unif") && (
              <Field label={t("inspector.field.stdDeviation")} help="inspector.hints.stdDeviation">
                <DelayInput
                  id={`std-${transition.id}`}
                  valueSecs={transition.standard_deviation}
                  onChange={(secs) => updateTransition(transition.id, { standard_deviation: secs })}
                  readOnly={readOnly}
                  min={0}
                />
              </Field>
            )}
          </>
        )}
        <Field label={t("inspector.field.probability")} help="inspector.hints.probability">
          {readOnly ? (
            <ReadOnlyValue value={probPct != null ? `${probPct}%` : "—"} />
          ) : (
            <>
              <CommitField
                key={`prob-${transition.id}`}
                type="number"
                min={0}
                max={maxPct}
                step={1}
                defaultValue={probPct ?? ""}
                placeholder={t("inspector.field.probabilityNone")}
                onBlur={(e) => {
                  const raw = e.target.value.trim();
                  if (raw === "") {
                    if (transition.probability !== null) updateTransition(transition.id, { probability: null });
                    return;
                  }
                  const pct = Number.parseInt(raw, 10);
                  if (Number.isFinite(pct)) {
                    const clamped = Math.min(maxPct, Math.max(0, pct));
                    const decimal = clamped / 100;
                    if (decimal !== transition.probability) updateTransition(transition.id, { probability: decimal });
                  }
                }}
              />
              {groupInfos.map(({ place, totalExplicitPct, remainingPct, countUnset, eachUnsetPct }) => (
                <p key={place.id} className="text-[10px] leading-tight text-text-muted">
                  <span className="font-medium text-text-secondary">
                    {t("inspector.field.conflictExplicit", { name: place.name, total: totalExplicitPct })}
                  </span>
                  {countUnset > 0
                    ? t("inspector.field.conflictRemainingSplit", { remaining: remainingPct, count: countUnset, each: eachUnsetPct })
                    : remainingPct > 0
                      ? t("inspector.field.conflictRemainingUnallocated", { remaining: remainingPct })
                      : ""}
                </p>
              ))}
            </>
          )}
        </Field>
      </Section>
      <Section title={t("inspector.section.position")}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="x">
            {readOnly ? (
              <ReadOnlyValue value={String(transition.graphics.x)} />
            ) : (
              <CommitField
                key={`x-${transition.id}-${transition.graphics.x}`}
                type="number"
                step={1}
                defaultValue={transition.graphics.x}
                onBlur={(e) => {
                  const next = Number.parseFloat(e.target.value);
                  if (Number.isFinite(next) && next !== transition.graphics.x) {
                    updateTransition(transition.id, { graphics: { x: next, y: transition.graphics.y } });
                  }
                }}
              />
            )}
          </Field>
          <Field label="y">
            {readOnly ? (
              <ReadOnlyValue value={String(transition.graphics.y)} />
            ) : (
              <CommitField
                key={`y-${transition.id}-${transition.graphics.y}`}
                type="number"
                step={1}
                defaultValue={transition.graphics.y}
                onBlur={(e) => {
                  const next = Number.parseFloat(e.target.value);
                  if (Number.isFinite(next) && next !== transition.graphics.y) {
                    updateTransition(transition.id, { graphics: { x: transition.graphics.x, y: next } });
                  }
                }}
              />
            )}
          </Field>
        </div>
      </Section>
    </>
  );
}

function ArcView({ arc, net, readOnly }: { arc: PetriArc; net: PetriNetData; readOnly: boolean }) {
  const { t } = useTranslation();
  const updateArc = useEditorStore((s) => s.updateArc);
  const sourceLabel = labelForNode(t, net, arc.source_id);
  const targetLabel = labelForNode(t, net, arc.target_id);
  const translatedArcTypes = ARC_TYPE_VALUES.map((v) => ({
    value: v,
    label: t(`inspector.arcTypes.${v}`),
  }));
  return (
    <>
      <Section title={t("inspector.section.endpoints")}>
        <Field label={t("inspector.field.source")}>
          <ReadOnlyValue value={sourceLabel} />
        </Field>
        <Field label={t("inspector.field.target")}>
          <ReadOnlyValue value={targetLabel} />
        </Field>
      </Section>
      <Section title={t("inspector.section.behavior")}>
        <Field label={t("inspector.field.type")}>
          {readOnly ? (
            <ReadOnlyValue value={t(`inspector.arcTypes.${arc.arc_type}`)} />
          ) : (
            <Select
              value={arc.arc_type}
              onChange={(value) => updateArc(arc.id, { arc_type: value })}
              options={translatedArcTypes}
            />
          )}
        </Field>
        <Field label={t("inspector.field.weight")}>
          {readOnly ? (
            <ReadOnlyValue value={String(arc.weight)} />
          ) : (
            <CommitField
              key={`w-${arc.id}`}
              type="number"
              min={1}
              step={1}
              defaultValue={arc.weight}
              onBlur={(e) => {
                const next = clampInt(e.target.value, 1);
                if (next !== arc.weight) updateArc(arc.id, { weight: next });
              }}
            />
          )}
        </Field>
      </Section>
    </>
  );
}

function ObjectFrameView({ frame, readOnly }: { frame: ObjectFrame; readOnly: boolean }) {
  const { t } = useTranslation();
  const renameObject = useEditorStore((s) => s.renameObject);
  const setObjectPriority = useEditorStore((s) => s.setObjectPriority);
  return (
    <Section title={t("inspector.section.identification")}>
      <Field label={t("inspector.field.id")}>
        <ReadOnlyValue value={frame.id} />
      </Field>
      <Field label={t("inspector.field.name")}>
        {readOnly ? (
          <ReadOnlyValue value={frame.name} />
        ) : (
          <CommitField
            key={`name-${frame.id}`}
            defaultValue={frame.name}
            onBlur={(e) => {
              const next = e.target.value.trim();
              if (next && next !== frame.name) renameObject(frame.id, next);
            }}
          />
        )}
      </Field>
      <Field label={t("inspector.field.priority")} help="inspector.hints.priority">
        {readOnly ? (
          <ReadOnlyValue value={String(frame.priority)} />
        ) : (
          <CommitField
            key={`priority-${frame.id}`}
            type="number"
            min={0}
            step={1}
            defaultValue={frame.priority}
            onBlur={(e) => {
              const next = clampInt(e.target.value, 0);
              if (next !== frame.priority) setObjectPriority(frame.id, next);
            }}
          />
        )}
      </Field>
    </Section>
  );
}

function ObjectLinkView({
  link,
  net,
  readOnly,
}: {
  link: ObjectLink;
  net: PetriNetData;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const updateObjectLink = useEditorStore((s) => s.updateObjectLink);
  const sourceLabel = labelForNode(t, net, link.sourceId);
  const targetLabel = labelForNode(t, net, link.targetId);
  const isFusion = link.type === "placeFusion";
  const isPlaceToTransition = link.type === "placeToTransition";
  return (
    <>
      <Section title={t("inspector.section.endpoints")}>
        <Field label={t("inspector.field.type")}>
          <ReadOnlyValue value={t(`inspector.linkTypes.${link.type}`)} />
        </Field>
        <Field label={t("inspector.field.source")}>
          <ReadOnlyValue value={sourceLabel} />
        </Field>
        <Field label={t("inspector.field.target")}>
          <ReadOnlyValue value={targetLabel} />
        </Field>
      </Section>
      {!isFusion && (
        <Section title={t("inspector.section.behavior")}>
          <Field label={t("inspector.field.weight")}>
            {readOnly ? (
              <ReadOnlyValue value={String(link.quantity)} />
            ) : (
              <CommitField
                key={`q-${link.id}`}
                type="number"
                min={1}
                step={1}
                defaultValue={link.quantity}
                onBlur={(e) => {
                  const next = clampInt(e.target.value, 1);
                  if (next !== link.quantity) updateObjectLink(link.id, { quantity: next });
                }}
              />
            )}
          </Field>
          {isPlaceToTransition && (
            <label className="flex items-center gap-2 text-sm text-text-primary">
              <input
                type="checkbox"
                checked={link.informational ?? false}
                disabled={readOnly}
                onChange={(e) => updateObjectLink(link.id, { informational: e.target.checked })}
              />
              {t("inspector.field.informational")}
            </label>
          )}
        </Section>
      )}
    </>
  );
}

function labelForNode(t: TFunction, net: PetriNetData, id: string): string {
  const place = net.places.find((p) => p.id === id);
  if (place) return t("inspector.field.placeLabel", { name: place.name });
  const trans = net.transitions.find((tr) => tr.id === id);
  if (trans) return t("inspector.field.transitionLabel", { name: trans.name });
  return id;
}

function clampInt(raw: string, min: number): number {
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return min;
  return Math.max(min, Math.trunc(n));
}
