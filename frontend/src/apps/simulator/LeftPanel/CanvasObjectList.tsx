import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye, EyeOff, Frame, MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ObjectFrame } from "@/types/petri";
import { useEditorStore } from "@/stores/editor-store";
import { useAuthStore } from "@/stores/auth-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { getObjects, membersOf } from "@/lib/petri-object-model";
import { saveCanvasObjectToLibrary } from "@/lib/petri-object-library";
import { DropdownMenu } from "@/components/common/DropdownMenu";
import { toast } from "@/stores/toast-store";
import { PaletteSection } from "./PaletteSection";

/**
 * The Petri-objects that exist on the current canvas, as opposed to the
 * library sections above it. Creating an object on the canvas makes it appear
 * here; from here it can be focused, hidden, edited, published to the library
 * or dissolved.
 */
export function CanvasObjectList() {
  const { t } = useTranslation();
  const net = useEditorStore((s) => s.net);
  const [expanded, setExpanded] = useState(true);
  const objects = getObjects(net);

  return (
    <PaletteSection
      label={t("objectPalette.onCanvas")}
      count={objects.length}
      expanded={expanded}
      onToggle={() => setExpanded((v) => !v)}
    >
      {objects.length === 0 ? (
        <p className="px-2 py-2 text-[10px] text-text-muted">
          <span className="block">{t("objectPalette.noCanvasObjectsLine1")}</span>
          <span className="block">{t("objectPalette.noCanvasObjectsLine2")}</span>
        </p>
      ) : (
        objects.map((frame) => (
          <CanvasObjectItem
            key={frame.id}
            frame={frame}
            memberCount={membersOf(net, frame.id).length}
          />
        ))
      )}
    </PaletteSection>
  );
}

function CanvasObjectItem({
  frame,
  memberCount,
}: {
  frame: ObjectFrame;
  memberCount: number;
}) {
  const { t } = useTranslation();
  const selected = useEditorStore((s) => s.selection.some((r) => r.id === frame.id));
  const setSelection = useEditorStore((s) => s.setSelection);
  const toggleObjectCollapsed = useEditorStore((s) => s.toggleObjectCollapsed);
  const ungroupObject = useEditorStore((s) => s.ungroupObject);
  const duplicateObject = useEditorStore((s) => s.duplicateObject);
  const deleteObject = useEditorStore((s) => s.deleteObject);
  const openObjectTab = useCanvasTabsStore((s) => s.openObjectTab);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const handleSaveToLibrary = useCallback(async () => {
    const result = await saveCanvasObjectToLibrary(frame.id);
    if (result.ok) {
      toast(t("canvas.contextMenu.saveToLibraryDone", { name: result.name }), "success");
    } else if (result.reason === "empty") {
      toast(t("canvas.contextMenu.saveToLibraryEmpty"), "error");
    } else if (result.reason === "failed") {
      toast(result.error ?? t("canvas.contextMenu.saveToLibraryFailed"), "error");
    }
  }, [frame.id, t]);

  return (
    <div
      className={cn(
        "group flex items-center gap-1.5 px-2 py-1 text-[11px]",
        selected
          ? "bg-surface-hover text-text-primary"
          : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
      )}
    >
      <Frame size={12} className="shrink-0 text-text-muted/70" />
      <button
        type="button"
        onClick={() => setSelection([{ id: frame.id, kind: "object" }])}
        className="min-w-0 flex-1 truncate text-left"
        title={frame.name}
      >
        {frame.name}
      </button>
      <span className="shrink-0 text-[10px] text-text-muted/70">{memberCount}</span>
      <button
        type="button"
        onClick={() => toggleObjectCollapsed(frame.id)}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-surface-hover"
        title={frame.collapsed ? t("objectFrame.expand") : t("objectFrame.collapse")}
      >
        {frame.collapsed ? <Eye size={12} /> : <EyeOff size={12} />}
      </button>
      <button
        ref={menuButtonRef}
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded",
          "opacity-0 transition-opacity group-hover:opacity-100",
          "hover:bg-surface-hover",
          menuOpen && "opacity-100",
        )}
      >
        <MoreVertical size={12} />
      </button>
      <DropdownMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        anchorEl={menuButtonRef.current}
        items={[
          {
            key: "edit",
            label: t("canvas.contextMenu.editObject"),
            onClick: () => openObjectTab(frame.id),
          },
          {
            key: "duplicate",
            label: t("canvas.contextMenu.duplicateObject"),
            onClick: () => duplicateObject(frame.id),
          },
          {
            key: "save",
            label: t("canvas.contextMenu.saveToLibrary"),
            disabled: !isAuthenticated,
            onClick: () => void handleSaveToLibrary(),
          },
          {
            key: "ungroup",
            label: t("canvas.contextMenu.ungroup"),
            separatorBefore: true,
            onClick: () => ungroupObject(frame.id),
          },
          {
            key: "delete",
            label: t("canvas.contextMenu.deleteObjectWithContents"),
            danger: true,
            onClick: () => deleteObject(frame.id, { keepContents: false }),
          },
        ]}
      />
    </div>
  );
}
