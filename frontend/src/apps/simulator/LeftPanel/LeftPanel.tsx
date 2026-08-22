import { useState } from "react";
import { Wrench, Puzzle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { ToolPalette } from "./ToolPalette";
import { ObjectPalette } from "./ObjectPalette";

type Tab = "tools" | "objects";

export function LeftPanel() {
  const [tab, setTab] = useState<Tab>("tools");

  return (
    <div className="flex h-full w-48 shrink-0 flex-col border-r border-border bg-surface-secondary">
      <div className="flex shrink-0 border-b border-border">
        <TabButton
          active={tab === "tools"}
          onClick={() => setTab("tools")}
          icon={Wrench}
          label="Tools"
        />
        <TabButton
          active={tab === "objects"}
          onClick={() => setTab("objects")}
          icon={Puzzle}
          label="Petri Objects"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "tools" && <ToolPalette layout="list" />}
        {tab === "objects" && <ObjectPalette />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={cn(
        // Tight, because two tabs share a 192px panel and "Petri Objects" is
        // the longer of them. The label truncates rather than overflowing if
        // a translation is longer still; the title attribute keeps it
        // readable when it does.
        "flex min-w-0 flex-1 items-center justify-center gap-1 px-1 py-1.5",
        "text-[10px] font-medium transition-colors",
        active
          ? "border-b-2 border-accent text-accent"
          : "text-text-muted hover:text-text-primary",
      )}
    >
      <Icon size={12} className="shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}
