// Prompt templates per page, filled from what the page already shows; the Ask box offers the first one that
// continues what was typed, and Tab accepts it.

export type PageContext = "home" | "traces" | "schedules" | "approvals" | "people" | "audit" | "evals";

const TEMPLATES: Record<PageContext, readonly string[]> = {
  home: [
    "What needs my attention today?",
    "Which runs failed in the last 24 hours, and why?",
    "Which agent used the most tokens this week?",
  ],
  traces: ["Why is this trace slower than the last successful run?", "Which tool call failed, and why?"],
  schedules: ["Why did this schedule fail?", "When did this schedule last succeed?"],
  approvals: ["Which approvals have been waiting the longest?", "Who usually approves refund_customer?"],
  people: ["Who can publish agents on this instance?", "Why can't this person see traces?"],
  audit: ["Who changed access roles this week?", "What changed in Studio yesterday?"],
  evals: ["Which cases regressed in the latest evaluation?", "Is the newest version safe to publish?"],
};

/** Templates for a page, with questions about what's failing first (e.g. ["daily-brief"] → "Why did …"). */
export function suggestionsFor(page: PageContext, failing: readonly string[] = []): string[] {
  const named = failing.slice(0, 3).map((name) => `Why did ${name} fail last night?`);
  return [...named, ...TEMPLATES[page]];
}

/** The rest of the first template that continues `typed` (case-insensitive), or "" when none does. */
export function completion(typed: string, templates: readonly string[]): string {
  const start = typed.trimStart();
  const match = templates.find(
    (template) => template.length > start.length && template.toLowerCase().startsWith(start.toLowerCase()),
  );
  return match ? match.slice(start.length) : "";
}
