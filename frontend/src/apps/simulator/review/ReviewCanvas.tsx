import { useEffect, useMemo, useRef, useState } from "react";
import {
    ReactFlow,
    Background,
    Controls,
    type ReactFlowInstance,
} from "@xyflow/react";
import { useTranslation } from "react-i18next";
import { buildGraph, NODE_TYPES, EDGE_TYPES } from "../EditorCanvas";
import { useUiStore } from "@/stores/ui-store";
import { useEditorStore } from "@/stores/editor-store";
import type { PetriNetData, SimulationSnapshot } from "@/types/petri";
import type { BundleInfo, Finding } from "@/lib/training-client";

export function imageRegion(
    info: BundleInfo,
    start: { x: number; y: number },
    end: { x: number; y: number },
): Finding["region"] | undefined {
    const g = info.geometry;
    if (!g.image || !g.transform || !info.image_sha256) return;
    const { origin_x: ox, origin_y: oy, scale } = g.transform;
    const x = Math.max(0, (Math.min(start.x, end.x) - ox) * scale);
    const y = Math.max(0, (Math.min(start.y, end.y) - oy) * scale);
    const right = Math.min(
        g.image.width,
        (Math.max(start.x, end.x) - ox) * scale,
    );
    const bottom = Math.min(
        g.image.height,
        (Math.max(start.y, end.y) - oy) * scale,
    );
    if (right <= x || bottom <= y) return;
    return {
        coordinate_system: "image-pixels",
        image_sha256: info.image_sha256,
        x,
        y,
        width: right - x,
        height: bottom - y,
    };
}

interface Props {
    info: BundleInfo;
    mode: "inspect" | "finding" | "area";
    snapshot?: SimulationSnapshot | null;
    onInspect: (id: string) => void;
    onFinding: (finding: Partial<Finding>, label?: string) => void;
}

export function ReviewCanvas({
    info,
    mode,
    snapshot = null,
    onInspect,
    onFinding,
}: Props) {
    const { t } = useTranslation();
    const theme = useUiStore((s) => s.resolvedTheme);
    const edgeStyle = useEditorStore((s) => s.edgeStyle);
    const frameStyle = useEditorStore((s) => s.frameStyle);
    const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
    const [selected, setSelected] = useState<string | null>(null);
    const [box, setBox] = useState<{
        x: number;
        y: number;
        endX: number;
        endY: number;
    } | null>(null);
    const rf = useRef<{
        screenToFlowPosition: ReactFlowInstance["screenToFlowPosition"];
        fitView: (options?: { padding?: number }) => Promise<boolean>;
    } | null>(null);
    const container = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!container.current || typeof ResizeObserver === "undefined") return;
        let timer: ReturnType<typeof setTimeout>;
        const observer = new ResizeObserver(() => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                void rf.current?.fitView({ padding: 0.15 });
            }, 100);
        });
        observer.observe(container.current);
        return () => {
            clearTimeout(timer);
            observer.disconnect();
        };
    }, []);
    const start = useRef<{
        screen: { x: number; y: number };
        flow: { x: number; y: number };
    } | null>(null);
    const viewNet = useMemo<PetriNetData>(
        () => ({
            ...info.net_data,
            objects: info.net_data.objects?.map((o) => ({
                ...o,
                collapsed: collapsed.has(o.id),
            })),
        }),
        [info, collapsed],
    );
    const graph = useMemo(
        () =>
            buildGraph(
                viewNet,
                new Set(selected ? [selected] : []),
                null,
                snapshot,
                edgeStyle,
                frameStyle,
                (id) =>
                    setCollapsed((prev) => {
                        const next = new Set(prev);
                        if (next.has(id)) next.delete(id);
                        else next.add(id);
                        return next;
                    }),
                (id) => onInspect(id),
                undefined,
                false,
            ),
        [viewNet, selected, snapshot, edgeStyle, frameStyle, onInspect],
    );
    const nodes = useMemo(
        () =>
            graph.nodes.map((node) => ({
                ...node,
                draggable: false,
                data: { ...node.data, locked: true },
            })),
        [graph.nodes],
    );
    function click(id: string) {
        setSelected(id);
        onInspect(id);
        if (mode === "finding") {
            const source = info.source_element_map[id];
            onFinding(
                { view_id: "main", ...(source ? { element_id: source } : {}) },
                [
                    ...viewNet.places,
                    ...viewNet.transitions,
                    ...(viewNet.objects ?? []),
                ].find((e) => e.id === id)?.name,
            );
        }
    }
    return (
        <div
            ref={container}
            className="relative h-full min-h-64 w-full"
            aria-label={t("review.liveCanvas")}
            onPointerDownCapture={(event) => {
                if (
                    mode !== "area" ||
                    event.button !== 0 ||
                    !rf.current ||
                    (event.target as HTMLElement).closest("button")
                )
                    return;
                event.preventDefault();
                event.stopPropagation();
                event.currentTarget.setPointerCapture(event.pointerId);
                start.current = {
                    screen: { x: event.clientX, y: event.clientY },
                    flow: rf.current.screenToFlowPosition({
                        x: event.clientX,
                        y: event.clientY,
                    }),
                };
                const rect = event.currentTarget.getBoundingClientRect();
                setBox({
                    x: event.clientX - rect.left,
                    y: event.clientY - rect.top,
                    endX: event.clientX - rect.left,
                    endY: event.clientY - rect.top,
                });
            }}
            onPointerMoveCapture={(event) => {
                if (!start.current) return;
                const rect = event.currentTarget.getBoundingClientRect();
                setBox((old) =>
                    old
                        ? {
                              ...old,
                              endX: event.clientX - rect.left,
                              endY: event.clientY - rect.top,
                          }
                        : null,
                );
            }}
            onPointerUpCapture={(event) => {
                const initial = start.current;
                if (!initial || !rf.current) return;
                event.stopPropagation();
                start.current = null;
                setBox(null);
                if (event.currentTarget.hasPointerCapture(event.pointerId))
                    event.currentTarget.releasePointerCapture(event.pointerId);
                const region = imageRegion(
                    info,
                    initial.flow,
                    rf.current.screenToFlowPosition({
                        x: event.clientX,
                        y: event.clientY,
                    }),
                );
                if (region)
                    onFinding(
                        { view_id: "main", region },
                        t("review.selectedArea"),
                    );
            }}
            onPointerCancel={() => {
                start.current = null;
                setBox(null);
            }}
        >
            <ReactFlow
                key={info.revision_id}
                nodes={nodes}
                edges={graph.edges}
                nodeTypes={NODE_TYPES}
                edgeTypes={EDGE_TYPES}
                nodesDraggable={false}
                nodesConnectable={false}
                edgesReconnectable={false}
                deleteKeyCode={null}
                onNodeClick={(_, node) => click(node.id)}
                onEdgeClick={(_, edge) => click(edge.id)}
                onInit={(instance) => {
                    rf.current = instance;
                }}
                fitView
                minZoom={0.05}
                maxZoom={4}
                panOnDrag={mode === "area" ? [1, 2] : true}
                colorMode={theme}
                proOptions={{ hideAttribution: true }}
            >
                <Background gap={24} />
                <Controls showInteractive={false} />
            </ReactFlow>
            {box && (
                <div
                    className="pointer-events-none absolute border-2 border-amber-500 bg-amber-400/15"
                    style={{
                        left: Math.min(box.x, box.endX),
                        top: Math.min(box.y, box.endY),
                        width: Math.abs(box.endX - box.x),
                        height: Math.abs(box.endY - box.y),
                    }}
                />
            )}
        </div>
    );
}
