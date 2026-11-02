// Context flows against stubbed APIs: cus_48213's memories with two likely duplicates and the source of one, the
// help_center knowledge base with a failed and a processing upload plus a test retrieval, a user_profile learning with
// the per-user deletion guard, and the daily brief in the workspace with where it came from. Each test keeps a
// full-page screenshot in its output folder.
import { expect, test, type Page } from "@playwright/test";

import { stubApi } from "./stubs";

const NOW = Date.now();
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();
const epochAgo = (minutes: number) => Math.round((NOW - minutes * 60_000) / 1000);
const page = <T>(items: T[], total = items.length) => ({
  data: items,
  meta: { page: 1, limit: 100, total_pages: 1, total_count: total },
});

async function shoot(target: Page, name: string) {
  await target.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

async function stubConfig(target: Page) {
  await target.route(/\/os\/config$/, (route) =>
    route.fulfill({
      json: {
        memory: { dbs: [{ db_id: "agno-postgres" }] },
        filesystem: {
          namespaces: [
            {
              namespace: "workspace",
              backend_type: "db",
              db_id: "agno-postgres",
              table_name: "agno_files",
              user_isolation: false,
              max_file_bytes: 1_048_576,
              max_namespace_bytes: 20 * 1024 ** 3,
              agents: [{ id: "daily-brief" }, { id: "kb-researcher", access: "read_only" }],
            },
          ],
        },
      },
    }),
  );
  await target.route(/\/os\/agents$/, (route) =>
    route.fulfill({
      json: [
        { id: "support-triage", name: "support-triage" },
        { id: "billing-agent", name: "billing-agent" },
        { id: "kb-researcher", name: "kb-researcher" },
      ],
    }),
  );
  await target.route(/\/os\/teams$|\/os\/workflows$/, (route) => route.fulfill({ json: [] }));
}

const MEMORIES = [
  ["Prefers email over phone for follow-ups.", ["preferences", "contact"], "support-triage", 120],
  ["Has a Pro annual plan, renewed in March 2026.", ["billing", "plan"], "billing-agent", 121],
  [
    "Was double-charged on order #4471; refund requested on 31 Oct.",
    ["billing", "refunds"],
    "support-triage",
    122,
  ],
  ["Was charged twice for order #4471.", ["billing"], "billing-agent", 123],
  ["Uses the mobile app on Android.", ["devices"], "support-triage", 4320],
  ["Uses the Android app.", ["devices"], "kb-researcher", 4321],
  [
    "Lives in Europe/Lisbon; replies sent after 18:00 are read the next morning.",
    ["preferences", "timezone"],
    "support-triage",
    7200,
  ],
  ["Asked twice how to export invoices as CSV.", ["billing", "exports"], "kb-researcher", 10080],
] as const;

test("memory: duplicates are flagged and a memory shows the input it came from", async ({
  page: browser,
}) => {
  await stubApi(browser);
  await stubConfig(browser);
  await browser.route(/\/os\/user_memory_stats/, (route) =>
    route.fulfill({
      json: page(
        [
          { user_id: "cus_48213", total_memories: 14, last_memory_updated_at: ago(120) },
          { user_id: "maya@northwind.dev", total_memories: 11, last_memory_updated_at: ago(20) },
          { user_id: "cus_51007", total_memories: 9, last_memory_updated_at: ago(300) },
          { user_id: "cus_39920", total_memories: 6, last_memory_updated_at: ago(1500) },
          { user_id: "dana@northwind.dev", total_memories: 4, last_memory_updated_at: ago(4400) },
          { user_id: "cus_60118", total_memories: 3, last_memory_updated_at: ago(10100) },
        ],
        312,
      ),
    }),
  );
  await browser.route(/\/os\/memories\?/, (route) =>
    route.fulfill({
      json: page(
        MEMORIES.map(([memory, topics, agent, minutes], index) => ({
          memory_id: `mem_48213_${String(index + 1)}`,
          memory,
          topics,
          agent_id: agent,
          user_id: "cus_48213",
          updated_at: ago(minutes),
        })),
        14,
      ),
    }),
  );
  await browser.route(/\/os\/memory_topics/, (route) =>
    route.fulfill({ json: ["billing", "preferences", "devices", "contact", "plan"] }),
  );
  await browser.route(/\/memories\/duplicates/, (route) =>
    route.fulfill({
      json: {
        user_id: "cus_48213",
        method: "trigram",
        threshold: 0.35,
        scanned: 8,
        total: 8,
        partial: false,
        duplicates: [
          { memory_id: "mem_48213_6", duplicate_of: "mem_48213_5", similarity: 0.67 },
          { memory_id: "mem_48213_4", duplicate_of: "mem_48213_3", similarity: 0.37 },
        ],
      },
    }),
  );
  await browser.route(/\/memories\/mem_48213_3\/source/, (route) =>
    route.fulfill({
      json: {
        memory_id: "mem_48213_3",
        user_id: "cus_48213",
        agent_id: "support-triage",
        team_id: null,
        session_id: "sess_9c41e2",
        run_id: "run_5e2a18",
        input: "My card was charged twice for order #4471. Can you refund one of them?",
        run_at: ago(125),
        run_status: "COMPLETED",
        method: "session_match",
        reason: null,
      },
    }),
  );
  await browser.route(/\/memories\/optimize$/, (route) =>
    route.fulfill({
      json: {
        user_id: "cus_48213",
        applied: false,
        memories: [
          {
            memory_id: "",
            memory: "Double-charged on order #4471; refund requested on 31 Oct and waiting for approval.",
            topics: [],
          },
          { memory_id: "", memory: "Uses the Android mobile app.", topics: [] },
          {
            memory_id: "",
            memory:
              "Prefers email follow-ups; in Europe/Lisbon, so replies after 18:00 are read the next morning.",
            topics: [],
          },
          {
            memory_id: "",
            memory: "Has a Pro annual plan renewed in March 2026; asked twice how to export invoices as CSV.",
            topics: [],
          },
        ],
        memories_before: 8,
        memories_after: 4,
        tokens_before: 410,
        tokens_after: 236,
        tokens_saved: 174,
        reduction_percentage: 42.4,
      },
    }),
  );

  await browser.goto("/i/prod-agentos/memory?user=cus_48213&memory=mem_48213_3");
  await expect(browser.getByRole("heading", { name: "cus_48213" })).toBeVisible();
  const list = browser.getByRole("list", { name: "Memories" });
  await expect(list.getByText("likely duplicate")).toHaveCount(2);
  const editor = browser.getByRole("complementary", { name: "Edit memory" });
  await expect(editor.getByText(/My card was charged twice for order #4471/)).toBeVisible();
  await expect(editor.getByRole("link", { name: "sess_9c41e2" })).toBeVisible();
  await shoot(browser, "memory");

  await browser.getByRole("button", { name: "Optimize memories" }).click();
  await expect(browser.getByRole("region", { name: "Optimization preview" })).toContainText(
    "Preview: 8 → 4 memories",
  );
  await shoot(browser, "memory-optimize");
});

const CONTENT = [
  [
    "c1",
    "android-release-notes.md",
    "Markdown",
    "38912",
    "processing",
    "Embedding, 62%",
    { product: "mobile" },
    1,
    "Uploaded by Priya Nair",
  ],
  [
    "c2",
    "invoices-export-guide.docx",
    "DOCX",
    "1258291",
    "failed",
    "Reader error: file is password-protected",
    { category: "billing" },
    8000,
    "Uploaded by Sam Rivera",
  ],
  [
    "c3",
    "refund-policy-2026.pdf",
    "PDF",
    "421888",
    "completed",
    "48 chunks",
    { category: "billing" },
    5000,
    "Uploaded by Maya Chen",
  ],
  [
    "c4",
    "help-center articles",
    "URL",
    "",
    "completed",
    "6,410 chunks",
    { source: "web" },
    6000,
    "help.northwind.dev/sitemap.xml",
  ],
  [
    "c5",
    "s3://northwind-kb/macros/",
    "S3",
    "",
    "completed",
    "388 chunks",
    { source: "macros" },
    7400,
    "Remote source · northwind-kb",
  ],
  [
    "c6",
    "docs/changelog/",
    "GitHub",
    "",
    "completed",
    "301 chunks",
    { source: "changelog" },
    9000,
    "northwind/agent-platform",
  ],
  [
    "c7",
    "status-page-faq",
    "Text",
    "4096",
    "completed",
    "6 chunks",
    { category: "incidents" },
    12000,
    "Pasted text",
  ],
  [
    "c8",
    "outage-runbook.md",
    "Markdown",
    "22528",
    "completed",
    "31 chunks",
    { category: "incidents" },
    16000,
    "Uploaded by Dana Okafor",
  ],
] as const;

test("knowledge: content statuses, readers and a test retrieval", async ({ page: browser }) => {
  await stubApi(browser);
  await stubConfig(browser);
  await browser.route(/\/knowledge\/bases$/, (route) =>
    route.fulfill({
      json: {
        bases: [
          {
            id: "kb_help_center",
            name: "help_center",
            description: null,
            db_id: "agno-postgres",
            table: "help_center",
            entries: 16,
            vector_dbs: [
              {
                id: "pgvector",
                name: "PgVector ai.help_center",
                search_types: ["vector", "keyword", "hybrid"],
              },
            ],
            used_by: [
              { id: "support-triage", kind: "agent", name: "support-triage" },
              { id: "kb-researcher", kind: "agent", name: "kb-researcher" },
            ],
          },
          {
            id: "kb_billing_policies",
            name: "billing_policies",
            description: null,
            db_id: "agno-postgres",
            table: "billing_policies",
            entries: 86,
            vector_dbs: [],
            used_by: [{ id: "billing-agent", kind: "agent", name: "billing-agent" }],
          },
        ],
      },
    }),
  );
  await browser.route(/\/instances\/[^/]+\/knowledge\/content/, (route) =>
    route.fulfill({
      json: {
        data: CONTENT.map(([id, name, kind, size, status, message, metadata, minutes, description]) => ({
          id,
          name,
          kind,
          type: null,
          size,
          status,
          status_message: message,
          metadata,
          description,
          created_at: ago(minutes),
          updated_at: ago(minutes),
        })),
        matching: 16,
        scanned: 16,
        total: 16,
        partial: false,
        counts: {
          total: 16,
          by_status: { completed: 14, processing: 1, partial: 0, failed: 1 },
          by_kind: { Markdown: 5, PDF: 3, URL: 2, DOCX: 2, S3: 2, GitHub: 1, Text: 1 },
        },
        page: 1,
        limit: 20,
      },
    }),
  );
  await browser.route(/\/os\/knowledge\/content\/c1\/status/, (route) =>
    route.fulfill({ json: { id: "c1", status: "processing", status_message: "Embedding, 62%" } }),
  );
  await browser.route(/\/os\/knowledge\/config/, (route) =>
    route.fulfill({
      json: {
        readers: { markdown: { id: "markdown", name: "Markdown" }, pdf: { id: "pdf", name: "PDF" } },
        chunkers: { MarkdownChunker: { key: "MarkdownChunker", name: "Markdown" } },
      },
    }),
  );
  await browser.route(/\/os\/knowledge\/search$/, (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: "a",
            content:
              "Duplicate charges caused by a payment retry are refunded in full to the original card within 5 to 10 business days. Do not promise an exact date.",
            name: "refund-policy-2026.pdf",
            reranking_score: 0.86,
            meta_data: { chunk: 14 },
          },
          {
            id: "b",
            content:
              "Apologise, confirm the order number and both charge amounts, then request the refund through the billing tool so it can be approved.",
            name: "s3://northwind-kb/macros/refund_duplicate.md",
            reranking_score: 0.81,
            meta_data: { chunk: 2 },
          },
          {
            id: "c",
            content:
              "If you see two charges for one order, one may be a temporary authorization that disappears within 3 days.",
            name: "help-center articles · /billing/charged-twice",
            reranking_score: 0.74,
            meta_data: { chunk: 1 },
          },
        ],
        meta: { page: 1, limit: 5, total_pages: 1, total_count: 3, search_time_ms: 142 },
      },
    }),
  );

  await browser.goto("/i/prod-agentos/knowledge");
  await expect(browser.getByRole("heading", { name: "help_center" })).toBeVisible();
  const table = browser.getByRole("table", { name: "Content" });
  await expect(table.getByText("Reader error: file is password-protected")).toBeVisible();
  await expect(browser.getByRole("button", { name: "1 failed" })).toBeVisible();
  await browser.getByRole("textbox", { name: "Query" }).fill("customer charged twice for one order");
  await browser.getByRole("button", { name: "Search", exact: true }).click();
  await expect(browser.getByRole("list", { name: "Top chunks" })).toContainText("0.86");
  await expect(browser.getByText(/3 results in 142 ms · hybrid search · reranking on/)).toBeVisible();
  await shoot(browser, "knowledge");
});

test("learnings: a readable profile and the guarded per-user deletion", async ({ page: browser }) => {
  await stubApi(browser);
  await stubConfig(browser);
  await browser.route(/\/learnings\/counts/, (route) =>
    route.fulfill({
      json: {
        counts: {
          user_profile: 212,
          user_memory: 198,
          session_context: 1406,
          entity_memory: 87,
          decision_log: 634,
        },
        id_schemes: { user_profile: "Deterministic id: user_profile_{user_id}" },
      },
    }),
  );
  await browser.route(/\/os\/learnings\?/, (route) =>
    route.fulfill({
      json: page(
        [
          {
            learning_id: "user_profile_cus_48213",
            learning_type: "user_profile",
            user_id: "cus_48213",
            agent_id: "support-triage",
            content: {
              preferred_channel: "email",
              timezone: "Europe/Lisbon",
              plan: "Pro annual",
              language: "en",
              open_issues: ["Refund for order #4471, waiting for approval"],
            },
            metadata: { confidence: 0.9, source_run: "run_5e2a18" },
            updated_at: epochAgo(120),
          },
          {
            learning_id: "user_profile_maya@northwind.dev",
            learning_type: "user_profile",
            user_id: "maya@northwind.dev",
            agent_id: "support-triage",
            content: { role: "Billing ops approver", answer_style: "Short, with a link to the trace" },
            metadata: { confidence: 0.8 },
            updated_at: epochAgo(600),
          },
          {
            learning_id: "user_profile_cus_51007",
            learning_type: "user_profile",
            user_id: "cus_51007",
            agent_id: "billing-agent",
            content: { plan: "Business", seats: 12, invoice_recipient: "Finance department" },
            metadata: { confidence: 0.85 },
            updated_at: epochAgo(1600),
          },
          {
            learning_id: "user_profile_cus_39920",
            learning_type: "user_profile",
            user_id: "cus_39920",
            agent_id: "support-triage",
            content: { language: "pt", plan: "Trial, cancelled" },
            metadata: { confidence: 0.7 },
            updated_at: epochAgo(3000),
          },
        ],
        212,
      ),
    }),
  );

  await browser.goto("/i/prod-agentos/learnings");
  const record = browser.getByRole("region", { name: "Record" });
  await expect(record.getByRole("heading", { name: "user_profile_cus_48213" })).toBeVisible();
  await expect(record.getByText("Preferred channel")).toBeVisible();
  const deletion = browser.getByRole("region", { name: "Delete learnings for cus_48213" });
  await expect(deletion.getByRole("button", { name: "Delete all" })).toBeDisabled();
  await shoot(browser, "learnings");
});

const BRIEF = `# Daily brief: Thu 30 Oct 2026

## Platform
- 820 runs, 19 failed (2.3%).
- Top model: claude-opus-5-5.

## Support
- Duplicate-charge tickets are rising; refunds go to Billing ops for approval.
- Android 4.12 sync errors: workaround added to help_center.

## Watch today
- Refunds waiting for approval: 2, oldest 5 h.
`;

test("files: the daily brief, its preview and where it came from", async ({ page: browser }) => {
  await stubApi(browser);
  await stubConfig(browser);
  const entries: Record<string, unknown[]> = {
    "": [
      { path: "reports", type: "directory", size_bytes: 40_000, updated_at: epochAgo(60) },
      { path: "exports", type: "directory", size_bytes: 900_000, updated_at: epochAgo(600) },
      { path: "sessions", type: "directory", size_bytes: 12_000, updated_at: epochAgo(900) },
      { path: "shared", type: "directory", size_bytes: 12_000, updated_at: epochAgo(9000) },
    ],
    reports: [
      { path: "reports/daily-brief", type: "directory", size_bytes: 36_000, updated_at: epochAgo(60) },
      { path: "reports/weekly-ops", type: "directory", size_bytes: 4_000, updated_at: epochAgo(3000) },
    ],
    "reports/daily-brief": [
      {
        path: "reports/daily-brief/2026-10-31.md",
        type: "file",
        size_bytes: 1_126,
        updated_at: epochAgo(60),
      },
      {
        path: "reports/daily-brief/2026-10-30.md",
        type: "file",
        size_bytes: 7_578,
        updated_at: epochAgo(1500),
      },
      {
        path: "reports/daily-brief/sources-2026-10-30.csv",
        type: "file",
        size_bytes: 18_432,
        updated_at: epochAgo(1501),
      },
      {
        path: "reports/daily-brief/2026-10-29.md",
        type: "file",
        size_bytes: 7_065,
        updated_at: epochAgo(2940),
      },
      {
        path: "reports/daily-brief/2026-10-28.md",
        type: "file",
        size_bytes: 7_270,
        updated_at: epochAgo(4380),
      },
      { path: "reports/daily-brief/index.json", type: "file", size_bytes: 2_048, updated_at: epochAgo(1500) },
    ],
  };
  await browser.route(/\/os\/filesystem\/entries/, (route) => {
    const directory = new URL(route.request().url()).searchParams.get("directory") ?? "";
    const list = entries[directory] ?? [];
    return route.fulfill({
      json: {
        namespace: "workspace",
        agent_ids: ["daily-brief"],
        directory,
        entries: list,
        usage: { file_count: 312, total_bytes: 2.1 * 1024 ** 3, bytes_limit: 20 * 1024 ** 3 },
        meta: { page: 1, limit: 100, total_pages: 1, total_count: list.length },
      },
    });
  });
  await browser.route(/\/os\/filesystem\/content/, (route) =>
    route.fulfill({
      json: {
        namespace: "workspace",
        agent_ids: ["daily-brief"],
        path: "reports/daily-brief/2026-10-30.md",
        content: BRIEF,
        size_bytes: 7_578,
        line_count: 12,
        truncated: false,
        offset: 0,
        limit: 100_000,
        updated_at: epochAgo(1500),
      },
    }),
  );
  await browser.route(/\/files\/provenance/, (route) =>
    route.fulfill({
      json: {
        path: "reports/daily-brief/2026-10-30.md",
        available: true,
        reason: null,
        exact: true,
        scanned_traces: 200,
        written: {
          action: "write",
          tool: "write_file",
          path: "reports/daily-brief/2026-10-30.md",
          trace_id: "tr_2f81c0",
          run_id: "run_2f81c0",
          session_id: "sess_b3f019",
          component_kind: "workflow",
          component_id: "daily-brief",
          step: "Compile brief",
          status: "OK",
          run_status: "OK",
          at: ago(1500),
        },
        partial: false,
        writes: [],
        read_by: [{ component_id: "kb-researcher", step: null, count: 2 }],
      },
    }),
  );

  await browser.goto(
    "/i/prod-agentos/files?dir=reports%2Fdaily-brief&file=reports%2Fdaily-brief%2F2026-10-30.md",
  );
  await expect(browser.getByText("2.1 GB of 20.0 GB")).toBeVisible();
  const preview = browser.getByRole("complementary", { name: "File preview" });
  await expect(preview.getByRole("heading", { name: "Daily brief: Thu 30 Oct 2026" })).toBeVisible();
  const origin = preview.getByRole("region", { name: "Where this came from" });
  await expect(origin.getByText("Compile brief")).toBeVisible();
  await expect(origin.getByText("kb-researcher, 2 times")).toBeVisible();
  await shoot(browser, "files");
});
