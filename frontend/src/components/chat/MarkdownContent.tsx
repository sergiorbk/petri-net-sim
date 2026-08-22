import { cn } from "@/lib/utils";
import { MermaidBlock } from "./MermaidBlock";

interface Props {
  content: string;
  className?: string;
}

// Inline formatting: bold, italic, inline-code, links
function renderInline(text: string, key: string): React.ReactNode {
  const RE =
    /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(`([^`]+)`)|\[([^\]]+)\]\(([^)]+)\)/g;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = RE.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(text.slice(last, m.index));
    }
    if (m[1]) {
      nodes.push(<strong key={m.index}>{m[2]}</strong>);
    } else if (m[3]) {
      nodes.push(<em key={m.index}>{m[4]}</em>);
    } else if (m[5]) {
      nodes.push(
        <code
          key={m.index}
          className="rounded bg-surface-hover px-1 py-0.5 font-mono text-[0.875em]"
        >
          {m[6]}
        </code>,
      );
    } else if (m[7]) {
      nodes.push(
        <a
          key={m.index}
          href={m[8]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline hover:text-accent-hover"
        >
          {m[7]}
        </a>,
      );
    }
    last = m.index + m[0].length;
  }

  if (last < text.length) {
    nodes.push(text.slice(last));
  }

  return nodes.length === 1 && typeof nodes[0] === "string" ? (
    nodes[0]
  ) : (
    <span key={key}>{nodes}</span>
  );
}

type Block =
  | { type: "h1" | "h2" | "h3"; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "code"; lang: string; text: string; closed: boolean }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "hr" };

function parseBlocks(md: string): Block[] {
  const lines = md.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      const closed = i < lines.length;
      if (closed) i++; // skip closing ```
      blocks.push({ type: "code", lang, text: codeLines.join("\n"), closed });
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Headings
    const h3 = line.match(/^###\s+(.*)/);
    const h2 = line.match(/^##\s+(.*)/);
    const h1 = line.match(/^#\s+(.*)/);
    if (h1) { blocks.push({ type: "h1", text: h1[1] }); i++; continue; }
    if (h2) { blocks.push({ type: "h2", text: h2[1] }); i++; continue; }
    if (h3) { blocks.push({ type: "h3", text: h3[1] }); i++; continue; }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Empty line — skip
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Table: header row | separator row | data rows
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1])
    ) {
      const parseRow = (r: string) =>
        r.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      const headers = parseRow(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(parseRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Paragraph: collect consecutive non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^(#{1,3}\s|[-*+]\s|\d+\.\s|```|---|===)/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", text: paraLines.join("\n") });
    }
  }

  return blocks;
}

export function MarkdownContent({ content, className }: Props) {
  const blocks = parseBlocks(content);

  return (
    <div className={cn("space-y-2 text-sm leading-relaxed", className)}>
      {blocks.map((block, i) => {
        const k = String(i);
        switch (block.type) {
          case "h1":
            return (
              <p key={k} className="text-base font-bold">
                {renderInline(block.text, k)}
              </p>
            );
          case "h2":
            return (
              <p key={k} className="font-semibold">
                {renderInline(block.text, k)}
              </p>
            );
          case "h3":
            return (
              <p key={k} className="font-medium">
                {renderInline(block.text, k)}
              </p>
            );
          case "paragraph":
            return (
              <p key={k} className="whitespace-pre-wrap">
                {renderInline(block.text, k)}
              </p>
            );
          case "ul":
            return (
              <ul key={k} className="ml-4 list-disc space-y-0.5">
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item, `${k}-${j}`)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={k} className="ml-4 list-decimal space-y-0.5">
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item, `${k}-${j}`)}</li>
                ))}
              </ol>
            );
          case "table":
            return (
              <div key={k} className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr>
                      {block.headers.map((h, j) => (
                        <th
                          key={j}
                          className="border border-border bg-surface-secondary px-3 py-1.5 text-left font-semibold text-text-primary"
                        >
                          {renderInline(h, `${k}-h-${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className="border border-border px-3 py-1.5 text-text-primary"
                          >
                            {renderInline(cell, `${k}-${ri}-${ci}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "code":
            if (block.lang === "mermaid" && block.closed) {
              return <MermaidBlock key={k} code={block.text} />;
            }
            return (
              <pre
                key={k}
                className="overflow-x-auto rounded-lg bg-surface-secondary p-3 font-mono text-xs"
              >
                <code>{block.text}</code>
              </pre>
            );
          case "hr":
            return <hr key={k} className="border-border" />;
        }
      })}
    </div>
  );
}
