import { memo, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import type { EdgeProps } from "@xyflow/react";

/** What a connection on the canvas is, as far as the hover hint is concerned. */
export type ArcHintKind = "input" | "output" | "read" | "inhibitor" | "fusion";

/**
 * Wraps an edge so hovering it names the kind of connection and, in one line,
 * what it does: the canvas is also a teaching tool, and the line styles alone
 * do not explain themselves to someone meeting Petri-objects for the first time.
 *
 * The hint is an SVG <title> placed next to the edge's own paths. React Flow
 * renders every edge inside one <g>, and a <title> that is a child of a group
 * applies to everything in it, so the wide invisible hit path BaseEdge draws
 * already triggers it and none of the edge components needs to know.
 */
export function withArcHint(Edge: ComponentType<EdgeProps>) {
  const Hinted = memo((props: EdgeProps) => {
    const { t } = useTranslation();
    const kind = (props.data as { arcKind?: ArcHintKind } | undefined)?.arcKind;
    return (
      <>
        {kind && <title>{t(`canvas.arcHint.${kind}`)}</title>}
        <Edge {...props} />
      </>
    );
  });
  Hinted.displayName = `withArcHint(${Edge.displayName ?? Edge.name})`;
  return Hinted;
}
