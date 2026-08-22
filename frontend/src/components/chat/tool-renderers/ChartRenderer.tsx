import { useMemo } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { cn } from "@/lib/utils";
import type { AgentToolCall, AgentToolResult, ChatMessage } from "@/types/chat";

interface ChartPayload {
  type: "bar" | "line" | "pie";
  title?: string;
  data: Record<string, unknown>[];
  xKey?: string;
  yKey?: string;
  nameKey?: string;
  valueKey?: string;
}

const COLORS = [
  "var(--color-accent, #6366f1)",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
];

export function ChartRenderer({
  result,
}: {
  call: AgentToolCall;
  result: AgentToolResult;
  message: ChatMessage;
}) {
  const payload = useMemo(() => parsePayload(result.output), [result.output]);

  if (!payload) return null;

  return (
    <div
      className={cn(
        "mt-1 overflow-hidden rounded-lg border border-border bg-surface p-3",
      )}
    >
      {payload.title && (
        <p className="mb-2 text-xs font-medium text-text-primary">
          {payload.title}
        </p>
      )}
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart(payload)}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function renderChart(p: ChartPayload) {
  const xKey = p.xKey ?? "name";
  const yKey = p.yKey ?? "value";

  if (p.type === "line") {
    return (
      <LineChart data={p.data}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Line
          type="monotone"
          dataKey={yKey}
          stroke={COLORS[0]}
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    );
  }

  if (p.type === "pie") {
    const nameKey = p.nameKey ?? "name";
    const valueKey = p.valueKey ?? "value";
    return (
      <PieChart>
        <Pie
          data={p.data}
          dataKey={valueKey}
          nameKey={nameKey}
          cx="50%"
          cy="50%"
          outerRadius={70}
          label={({ name }) => name}
        >
          {p.data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    );
  }

  return (
    <BarChart data={p.data}>
      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
      <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
      <YAxis tick={{ fontSize: 11 }} />
      <Tooltip />
      <Bar dataKey={yKey} fill={COLORS[0]} radius={[4, 4, 0, 0]} />
    </BarChart>
  );
}

function parsePayload(raw: string): ChartPayload | null {
  try {
    const obj = JSON.parse(raw);
    if (
      obj &&
      typeof obj.type === "string" &&
      ["bar", "line", "pie"].includes(obj.type) &&
      Array.isArray(obj.data)
    ) {
      return obj as ChartPayload;
    }
  } catch {
    // not chart data
  }
  return null;
}
