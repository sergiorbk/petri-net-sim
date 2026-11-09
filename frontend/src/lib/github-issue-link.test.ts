import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ISSUE_TEMPLATES,
  NEW_ISSUE_URL,
  type IssueKind,
  issueLink,
} from "./github-issue-link";

const KINDS = Object.keys(ISSUE_TEMPLATES) as IssueKind[];
const TEMPLATE_DIR = resolve(__dirname, "../../../.github/ISSUE_TEMPLATE");

describe("issueLink", () => {
  it("opens the matching form on the repository", () => {
    for (const kind of KINDS) {
      const url = new URL(issueLink(kind, "TestAgent/1.0"));
      expect(`${url.origin}${url.pathname}`).toBe(NEW_ISSUE_URL);
      expect(url.searchParams.get("template")).toBe(ISSUE_TEMPLATES[kind]);
    }
  });

  it("puts the browser into a bug report", () => {
    const url = new URL(issueLink("bug", "TestAgent/1.0"));
    expect(url.searchParams.get("version")).toContain("TestAgent/1.0");
  });

  // GitHub drops a value whose field is gone without a word, so a renamed
  // id in a template has to fail here rather than in a stranger's report.
  it("only fills fields that exist in the templates", () => {
    for (const kind of KINDS) {
      const yaml = readFileSync(
        resolve(TEMPLATE_DIR, ISSUE_TEMPLATES[kind]),
        "utf8",
      );
      const params = new URL(issueLink(kind, "TestAgent/1.0")).searchParams;
      for (const [key, value] of params) {
        if (key === "template") continue;
        expect(yaml, `${ISSUE_TEMPLATES[kind]} lacks id ${key}`).toMatch(
          new RegExp(`id: ${key}\\r?\\n`),
        );
        if (key === "area") expect(yaml).toContain(`- ${value}`);
      }
    }
  });
});
