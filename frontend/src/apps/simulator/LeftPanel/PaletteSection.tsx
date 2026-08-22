import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface PaletteSectionProps {
  label: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

/** Collapsible group in the left panel, with the item count on the right. */
export function PaletteSection({
  label,
  count,
  expanded,
  onToggle,
  children,
}: PaletteSectionProps) {
  return (
    <div className="mb-1">
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex w-full items-center gap-1 px-2 py-1 text-left text-[11px]",
          "font-semibold uppercase tracking-wide text-text-muted",
          "hover:text-text-primary",
        )}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {label}
        <span className="ml-auto font-normal text-text-muted/70">{count}</span>
      </button>
      {expanded && <div className="flex flex-col">{children}</div>}
    </div>
  );
}
