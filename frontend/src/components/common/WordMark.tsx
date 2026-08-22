import { cn } from "@/lib/utils";

interface WordMarkProps {
  children: string;
  className?: string;
}

/**
 * A short word standing in where an icon would go.
 *
 * "MCP" and "API" are the names people already use for these two, and no
 * pictogram says either one: a plug and a webhook glyph both need a tooltip
 * before they mean anything. Shared between the activity bar and the settings
 * nav so the same entry point is recognisable in both.
 *
 * Colour is inherited, so it picks up the active and hover states of whatever
 * contains it, exactly as a lucide icon does.
 */
export function WordMark({ children, className }: WordMarkProps) {
  return (
    <span className={cn("font-bold leading-none tracking-tight", className)}>
      {children}
    </span>
  );
}
