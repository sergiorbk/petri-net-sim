import { version as appVersion } from "../../package.json";

/**
 * "New issue" addresses that open one of the repository's issue forms with the
 * environment already filled in. The report is filed in the browser, under the
 * reader's own GitHub account; an in-app channel with a token could sit beside
 * this later.
 *
 * GitHub fills a form field from the query parameter named after the field's
 * `id` in `.github/ISSUE_TEMPLATE/*.yml`, and a dropdown from the exact text of
 * one of its options. Those ids and options are a contract with every deployed
 * build: rename one and older builds stop filling it, silently.
 */
export const NEW_ISSUE_URL =
  "https://github.com/sergiorbk/petri-net-sim/issues/new";

export type IssueKind = "bug" | "feature" | "feedback";

export const ISSUE_TEMPLATES: Record<IssueKind, string> = {
  bug: "bug_report.yml",
  feature: "feature_request.yml",
  feedback: "feedback.yml",
};

/** Option text of the "area" dropdown in bug_report.yml and feature_request.yml. */
export const EDITOR_AREA = "Editor (canvas, frontend)";

export function issueLink(
  kind: IssueKind,
  userAgent: string = navigator.userAgent,
): string {
  const environment = `${appVersion}, ${userAgent}`;
  const fields: Record<string, string> = { template: ISSUE_TEMPLATES[kind] };
  if (kind === "bug") {
    fields.area = EDITOR_AREA;
    fields["how-run"] = `Web app at ${window.location.origin}`;
    fields.version = environment;
  } else if (kind === "feature") {
    fields.area = EDITOR_AREA;
  } else {
    fields.version = environment;
  }
  // URLSearchParams writes spaces as "+", which GitHub reads back as spaces.
  return `${NEW_ISSUE_URL}?${new URLSearchParams(fields).toString()}`;
}
