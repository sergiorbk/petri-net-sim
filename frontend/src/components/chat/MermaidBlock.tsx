import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { cn } from "@/lib/utils";

let mermaidInitialized = false;

function ensureInit() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "strict",
    fontFamily: "inherit",
  });
  mermaidInitialized = true;
}

let idCounter = 0;

interface Props {
  code: string;
  className?: string;
}

export function MermaidBlock({ code, className }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    ensureInit();
    const id = `mermaid-${++idCounter}`;

    let cancelled = false;
    mermaid
      .render(id, code)
      .then(({ svg }) => {
        if (!cancelled && el) {
          el.innerHTML = svg;
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <pre className="overflow-x-auto rounded-lg bg-surface-secondary p-3 font-mono text-xs text-red-500">
        {code}
      </pre>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "overflow-x-auto rounded-lg bg-surface-secondary p-3 [&_svg]:max-w-full",
        className,
      )}
    />
  );
}
