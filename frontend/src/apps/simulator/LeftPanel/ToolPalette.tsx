import {
  ArrowRight,
  Circle,
  Frame,
  Lasso,
  MousePointer2,
  Square,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useEditorStore, type EditorTool } from "@/stores/editor-store";

const DRAGGABLE_TOOLS = new Set<EditorTool>(["add-place", "add-transition"]);

interface ToolDef {
  id: EditorTool;
  labelKey: string;
  shortcut: string;
  icon: LucideIcon;
}

export const TOOLS: readonly ToolDef[] = [
  { id: "select",           labelKey: "toolPalette.select",          shortcut: "V", icon: MousePointer2 },
  { id: "select-box",       labelKey: "toolPalette.selectBox",       shortcut: "B", icon: Square },
  { id: "select-lasso",     labelKey: "toolPalette.selectLasso",     shortcut: "L", icon: Lasso },
  { id: "delete",           labelKey: "toolPalette.delete",          shortcut: "D", icon: Trash2 },
  { id: "add-place",        labelKey: "toolPalette.addPlace",        shortcut: "P", icon: Circle },
  { id: "add-transition",   labelKey: "toolPalette.addTransition",   shortcut: "T", icon: Square },
  { id: "add-arc",          labelKey: "toolPalette.addArc",          shortcut: "A", icon: ArrowRight },
  { id: "add-object",       labelKey: "toolPalette.addObject",       shortcut: "F", icon: Frame },
];

const EDIT_TOOLS = new Set<EditorTool>(["select", "select-box", "select-lasso", "delete"]);
const ADD_TOOLS  = new Set<EditorTool>(["add-place", "add-transition", "add-arc", "add-object"]);

export function ToolPalette({ layout = "icons" }: { layout?: "icons" | "list" }) {
  const { t } = useTranslation();
  const tool = useEditorStore((s) => s.tool);
  const setTool = useEditorStore((s) => s.setTool);

  if (layout === "list") {
    const editTools = TOOLS.filter(({ id }) => EDIT_TOOLS.has(id));
    const addTools  = TOOLS.filter(({ id }) => ADD_TOOLS.has(id));

    const renderToolButton = ({ id, labelKey, shortcut, icon: Icon }: ToolDef) => {
      const label = t(labelKey);
      const active = tool === id;
      const draggable = DRAGGABLE_TOOLS.has(id);
      return (
        <button
          key={id}
          type="button"
          onClick={() => setTool(id)}
          draggable={draggable}
          onDragStart={draggable ? (e) => {
            const img = document.createElement("div");
            img.style.position = "absolute";
            img.style.left = "-9999px";
            img.style.background = "white";
            img.style.border = "3px solid " + (id === "add-place" ? "#71717a" : "#27272a");
            if (id === "add-place") {
              img.style.width = "56px";
              img.style.height = "56px";
              img.style.borderRadius = "50%";
            } else {
              img.style.width = "28px";
              img.style.height = "64px";
            }
            document.body.appendChild(img);
            e.dataTransfer.setData("application/editor-tool", id);
            e.dataTransfer.effectAllowed = "copy";
            e.dataTransfer.setDragImage(img, id === "add-place" ? 28 : 14, id === "add-place" ? 28 : 32);
            setTimeout(() => img.remove(), 0);
          } : undefined}
          aria-label={`${label} (${shortcut})`}
          aria-pressed={active}
          title={draggable ? `${label} (${shortcut}) — ${t("toolPalette.dragToPlace")}` : `${label} (${shortcut})`}
          className={cn(
            "flex items-center gap-2 px-2.5 py-1.5 text-[11px]",
            "transition-colors focus-visible:outline-2",
            "focus-visible:outline-offset-2 focus-visible:outline-accent",
            draggable && "cursor-grab active:cursor-grabbing",
            active
              ? "bg-accent/10 font-medium text-accent"
              : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
          )}
        >
          <Icon size={14} className="shrink-0" />
          {/* text-left because a button centres its text by default, and the
              span is flex-1: without this the label floats in the middle of
              the row instead of sitting next to its icon. */}
          <span className="flex-1 truncate text-left">{label}</span>
          <kbd className="text-[9px] font-normal text-text-muted">{shortcut}</kbd>
        </button>
      );
    };

    return (
      <div role="toolbar" aria-label="Editor tools" aria-orientation="vertical" className="flex flex-col py-1">
        <div className="flex flex-col gap-0.5">
          {editTools.map(renderToolButton)}
        </div>
        <div className="mt-2 border-t border-border pt-2">
          <p className="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
            {t("toolPalette.addElements")}
          </p>
          <div className="flex flex-col gap-0.5">
            {addTools.map(renderToolButton)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      role="toolbar"
      aria-label="Editor tools"
      aria-orientation="vertical"
      className={cn(
        "flex h-full w-12 flex-col items-center gap-1 border-r",
        "border-border bg-surface-secondary py-2",
      )}
    >
      {TOOLS.map(({ id, labelKey, shortcut, icon: Icon }) => {
        const label = t(labelKey);
        const active = tool === id;
        const draggable = DRAGGABLE_TOOLS.has(id);
        return (
          <button
            key={id}
            type="button"
            onClick={() => setTool(id)}
            draggable={draggable}
            onDragStart={draggable ? (e) => {
              const img = document.createElement("div");
              img.style.position = "absolute";
              img.style.left = "-9999px";
              img.style.background = "white";
              img.style.border = "3px solid " + (id === "add-place" ? "#71717a" : "#27272a");
              if (id === "add-place") {
                img.style.width = "56px";
                img.style.height = "56px";
                img.style.borderRadius = "50%";
              } else {
                img.style.width = "28px";
                img.style.height = "64px";
              }
              document.body.appendChild(img);
              e.dataTransfer.setData("application/editor-tool", id);
              e.dataTransfer.effectAllowed = "copy";
              e.dataTransfer.setDragImage(img, id === "add-place" ? 28 : 14, id === "add-place" ? 28 : 32);
              setTimeout(() => img.remove(), 0);
            } : undefined}
            aria-label={`${label} (${shortcut})`}
            aria-pressed={active}
            title={draggable ? `${label} (${shortcut}) — ${t("toolPalette.dragToPlace")}` : `${label} (${shortcut})`}
            className={cn(
              "relative flex h-9 w-9 items-center justify-center rounded-md",
              "transition-colors focus-visible:outline-2",
              "focus-visible:outline-offset-2 focus-visible:outline-accent",
              draggable && "cursor-grab active:cursor-grabbing",
              active
                ? "bg-accent text-white"
                : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
            )}
          >
            <Icon size={18} />
            <span
              aria-hidden="true"
              className={cn(
                "pointer-events-none absolute bottom-0.5 right-0.5",
                "text-[9px] font-semibold leading-none",
                active ? "text-white/80" : "text-text-muted",
              )}
            >
              {shortcut}
            </span>
          </button>
        );
      })}
    </div>
  );
}
