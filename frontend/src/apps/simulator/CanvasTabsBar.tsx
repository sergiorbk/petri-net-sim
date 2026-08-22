import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Layers, ListTree, Save, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor-store";
import {
  canvasLevel,
  objectIdOf,
  useCanvasTabsStore,
  type CanvasTab,
} from "@/stores/canvas-tabs-store";
import { getObjects, objectLevel, objectsParentFirst } from "@/lib/petri-object-model";
import { toast } from "@/stores/toast-store";

/** How far one arrow press slides the strip. */
const SCROLL_STEP_PX = 220;

interface CanvasEntry {
  key: string;
  label: string;
  level: number;
  /** Open canvases can be activated and closed; the rest can only be opened. */
  open: boolean;
  active: boolean;
  /** Object this entry stands for — absent for the net's own canvas. */
  objectId: string | null;
}

/**
 * Horizontal navigator across the canvases of one net: the net itself at level
 * 0, the objects on it at level 1, objects built inside those at level 2, and
 * so on. It can show just the open canvases or every object in the net, so an
 * object can be reached without first finding it on the canvas.
 */
export function CanvasTabsBar() {
  const { t } = useTranslation();
  const tabs = useCanvasTabsStore((s) => s.tabs);
  const activeId = useCanvasTabsStore((s) => s.activeId);
  const activateTab = useCanvasTabsStore((s) => s.activateTab);
  const closeTab = useCanvasTabsStore((s) => s.closeTab);
  const openObjectTab = useCanvasTabsStore((s) => s.openObjectTab);
  const saveActiveObjectTab = useCanvasTabsStore((s) => s.saveActiveObjectTab);
  const setTabTitle = useCanvasTabsStore((s) => s.setTabTitle);

  const net = useEditorStore((s) => s.net);
  const netName = net.name;
  const dirty = useEditorStore((s) => s.dirty);

  const [showAll, setShowAll] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState({ left: false, right: false });

  // The active canvas owns its name in the editor store; mirror it onto the
  // entry so renaming a net or an object shows up here immediately.
  useEffect(() => {
    setTabTitle(activeId, netName);
  }, [activeId, netName, setTabTitle]);

  const activeTab = tabs.find((tab) => tab.id === activeId) ?? null;
  const activeLevel = activeTab ? canvasLevel(activeTab) : 0;

  const entries = useMemo<CanvasEntry[]>(() => {
    const openByObject = new Map<string, CanvasTab>();
    for (const tab of tabs) {
      const objectId = objectIdOf(tab);
      if (objectId) openByObject.set(objectId, tab);
    }

    const list: CanvasEntry[] = tabs.map((tab) => ({
      key: tab.id,
      label: (tab.id === activeId ? netName : tab.title) || t("canvasTabs.untitled"),
      level: canvasLevel(tab),
      open: true,
      active: tab.id === activeId,
      objectId: objectIdOf(tab),
    }));

    if (!showAll) return list;

    // Everything on the active canvas that has no canvas open yet, at the
    // level it would occupy once opened.
    for (const frame of objectsParentFirst(net)) {
      if (openByObject.has(frame.id)) continue;
      list.push({
        key: `object:${frame.id}`,
        label: frame.name,
        level: activeLevel + objectLevel(net, frame.id),
        open: false,
        active: false,
        objectId: frame.id,
      });
    }
    return list;
  }, [tabs, activeId, netName, showAll, net, activeLevel, t]);

  const syncOverflow = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setOverflow((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  useEffect(() => {
    syncOverflow();
    const el = scrollerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(syncOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [syncOverflow, entries.length]);

  const scrollBy = (delta: number) => {
    scrollerRef.current?.scrollBy({ left: delta, behavior: "smooth" });
  };

  /** Opening a nested object opens the chain of canvases leading down to it. */
  const openObjectChain = useCallback(
    (objectId: string) => {
      const byId = new Map(getObjects(net).map((o) => [o.id, o]));
      const chain: string[] = [];
      let current: string | undefined = objectId;
      const seen = new Set<string>();
      while (current && !seen.has(current)) {
        seen.add(current);
        chain.unshift(current);
        current = byId.get(current)?.objectId;
      }
      for (const id of chain) {
        if (!openObjectTab(id)) {
          toast(t("canvas.contextMenu.editObjectFailed"), "error");
          return;
        }
      }
    },
    [net, openObjectTab, t],
  );

  function handleSave() {
    if (saveActiveObjectTab()) toast(t("canvasTabs.saved"), "success");
    else toast(t("canvasTabs.saveFailed"), "error");
  }

  function handleClose(entry: CanvasEntry) {
    if (entry.active && dirty && !window.confirm(t("canvasTabs.confirmClose", { name: entry.label }))) {
      return;
    }
    closeTab(entry.key);
  }

  // Always rendered: the bar appearing and vanishing with the first object
  // made the whole canvas area jump, and an ever-present level strip is how
  // the user knows which canvas they are looking at in the first place.
  return (
    <div
      className={cn(
        "flex h-8 shrink-0 items-center gap-1 border-t border-border",
        "bg-surface-secondary px-1",
      )}
    >
      <ArrowButton
        direction="left"
        disabled={!overflow.left}
        onClick={() => scrollBy(-SCROLL_STEP_PX)}
        title={t("canvasTabs.scrollLeft")}
      />

      <div
        ref={scrollerRef}
        onScroll={syncOverflow}
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto scrollbar-none"
      >
        {entries.map((entry) => (
          <div
            key={entry.key}
            className={cn(
              "flex h-6 shrink-0 items-center gap-1.5 rounded px-1.5 text-[11px]",
              entry.active
                ? "bg-surface font-medium text-text-primary shadow-sm"
                : entry.open
                  ? "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                  : "text-text-muted/70 hover:bg-surface-hover hover:text-text-primary",
            )}
          >
            <button
              type="button"
              onClick={() =>
                entry.open
                  ? activateTab(entry.key)
                  : entry.objectId && openObjectChain(entry.objectId)
              }
              className="flex items-center gap-1.5"
              title={t("canvasTabs.levelHint", { level: entry.level, name: entry.label })}
            >
              <span
                className={cn(
                  "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm",
                  "text-[9px] font-semibold",
                  entry.active
                    ? "bg-accent text-white"
                    : "bg-surface-hover text-text-muted",
                )}
              >
                {entry.level}
              </span>
              {entry.objectId && <Layers size={10} className="shrink-0" />}
              <span className="max-w-[150px] truncate">{entry.label}</span>
              {entry.active && dirty && <span className="text-accent">•</span>}
            </button>
            {entry.open && entry.objectId && (
              <button
                type="button"
                onClick={() => handleClose(entry)}
                className="rounded p-0.5 hover:bg-surface-hover"
                title={t("canvasTabs.close")}
              >
                <X size={10} />
              </button>
            )}
          </div>
        ))}
      </div>

      <ArrowButton
        direction="right"
        disabled={!overflow.right}
        onClick={() => scrollBy(SCROLL_STEP_PX)}
        title={t("canvasTabs.scrollRight")}
      />

      <button
        type="button"
        onClick={() => setShowAll((v) => !v)}
        title={showAll ? t("canvasTabs.showOpenOnly") : t("canvasTabs.showAll")}
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded",
          showAll ? "bg-accent text-white" : "text-text-muted hover:bg-surface-hover",
        )}
      >
        <ListTree size={12} />
      </button>

      {activeTab && canvasLevel(activeTab) > 0 && (
        <button
          type="button"
          onClick={handleSave}
          className={cn(
            "flex h-6 shrink-0 items-center gap-1.5 rounded px-2",
            "bg-accent text-[11px] font-medium text-white",
          )}
        >
          <Save size={11} />
          {t("canvasTabs.save")}
        </button>
      )}
    </div>
  );
}

function ArrowButton({
  direction,
  disabled,
  onClick,
  title,
}: {
  direction: "left" | "right";
  disabled: boolean;
  onClick: () => void;
  title: string;
}) {
  const Icon = direction === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "flex h-6 w-5 shrink-0 items-center justify-center rounded",
        disabled
          ? "text-text-muted/30"
          : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
      )}
    >
      <Icon size={13} />
    </button>
  );
}
