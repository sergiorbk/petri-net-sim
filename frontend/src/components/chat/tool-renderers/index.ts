import type { ReactNode } from "react";
import type { AgentToolCall, AgentToolResult, ChatMessage } from "@/types/chat";
import { SimulationResultRenderer } from "./SimulationResultRenderer";
import { ChartRenderer } from "./ChartRenderer";

export type ToolRenderer = (props: {
  call: AgentToolCall;
  result: AgentToolResult;
  message: ChatMessage;
}) => ReactNode | null;

const TOOL_RENDERERS: Partial<Record<string, ToolRenderer>> = {
  run_simulation: SimulationResultRenderer,
  show_chart: ChartRenderer,
};

export function getToolRenderer(name: string): ToolRenderer | null {
  return TOOL_RENDERERS[name] ?? null;
}
