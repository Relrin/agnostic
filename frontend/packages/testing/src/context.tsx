// Context fixtures from the prototype's sample org: cus_48213's memories (two likely duplicates), the help_center
// knowledge base, learning records per type and the daily-brief workspace; plus MSW handlers for them.
import type {
  AgentOS,
  DataSubjectOut,
  DuplicatesOut,
  FileProvenanceOut,
  KnowledgeBasesOut,
  LearningCountsOut,
  MemorySourceOut,
  OptimizeOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { PROD } from "./sample-org";
import { GATEWAY } from "./operate";

const NOW = Date.now();
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();
const epochAgo = (minutes: number) => Math.round((NOW - minutes * 60_000) / 1000);

function page<T>(items: T[]) {
  return { data: items, meta: { page: 1, limit: 100, total_pages: 1, total_count: items.length } };
}

export const sampleMemoryUsers: AgentOS.UserStatsSchema[] = [
  { user_id: "cus_48213", total_memories: 14, last_memory_updated_at: ago(120) },
  { user_id: "maya@northwind.dev", total_memories: 11, last_memory_updated_at: ago(20) },
  { user_id: "cus_51007", total_memories: 9, last_memory_updated_at: ago(300) },
  { user_id: "cus_39920", total_memories: 6, last_memory_updated_at: ago(1500) },
];

function memory(
  index: number,
  text: string,
  topics: string[],
  agent: string,
  minutes: number,
): AgentOS.UserMemorySchema {
  return {
    memory_id: `mem_48213_${String(index)}`,
    memory: text,
    topics,
    agent_id: agent,
    user_id: "cus_48213",
    updated_at: ago(minutes),
  };
}

export const sampleMemories: AgentOS.UserMemorySchema[] = [
  memory(1, "Prefers email over phone for follow-ups.", ["preferences", "contact"], "support-triage", 120),
  memory(2, "Has a Pro annual plan, renewed in March 2026.", ["billing", "plan"], "billing-agent", 121),
  memory(
    3,
    "Was double-charged on order #4471; refund requested on 31 Oct.",
    ["billing", "refunds"],
    "support-triage",
    122,
  ),
  memory(4, "Was charged twice for order #4471.", ["billing"], "billing-agent", 123),
  memory(5, "Uses the mobile app on Android.", ["devices"], "support-triage", 4320),
  memory(6, "Uses the Android app.", ["devices"], "kb-researcher", 4321),
  memory(
    7,
    "Lives in Europe/Lisbon; replies sent after 18:00 are read the next morning.",
    ["preferences", "timezone"],
    "support-triage",
    7200,
  ),
  memory(8, "Asked twice how to export invoices as CSV.", ["billing", "exports"], "kb-researcher", 10080),
];

export const sampleDuplicates: DuplicatesOut = {
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
};

export const sampleMemorySource: MemorySourceOut = {
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
};

export const sampleOptimization: OptimizeOut = {
  user_id: "cus_48213",
  applied: false,
  memories: [
    {
      memory_id: "",
      memory: "Double-charged on order #4471; refund requested on 31 Oct and waiting for approval.",
      topics: ["billing"],
    },
    { memory_id: "", memory: "Uses the Android mobile app.", topics: ["devices"] },
  ],
  memories_before: 8,
  memories_after: 2,
  tokens_before: 410,
  tokens_after: 260,
  tokens_saved: 150,
  reduction_percentage: 36.6,
};

export const sampleKnowledgeBases: KnowledgeBasesOut = {
  bases: [
    {
      id: "kb_help_center",
      name: "help_center",
      description: "Customer-facing help articles and macros",
      db_id: "agno-postgres",
      table: "help_center",
      entries: 16,
      vector_dbs: [
        { id: "pgvector", name: "PgVector ai.help_center", search_types: ["vector", "keyword", "hybrid"] },
      ],
      used_by: [
        { id: "support-triage", kind: "agent", name: "Support triage" },
        { id: "kb-researcher", kind: "agent", name: "KB researcher" },
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
      used_by: [{ id: "billing-agent", kind: "agent", name: "Billing agent" }],
    },
  ],
};

function content(
  id: string,
  name: string,
  kind: string,
  size: string,
  status: AgentOS.ContentStatus,
  message: string,
  metadata: Record<string, string>,
  minutes: number,
  description?: string,
) {
  return {
    id,
    name,
    kind,
    type: kind === "Markdown" ? "text/markdown" : kind === "PDF" ? "application/pdf" : null,
    size,
    status,
    status_message: message,
    metadata,
    description: description ?? null,
    access_count: 12,
    created_at: ago(minutes),
    updated_at: ago(minutes),
  };
}

export const sampleContent = [
  content(
    "c1",
    "android-release-notes.md",
    "Markdown",
    "38912",
    "processing",
    "Embedding, 62%",
    { product: "mobile" },
    1,
    "Uploaded by Priya Nair",
  ),
  content(
    "c2",
    "invoices-export-guide.docx",
    "DOCX",
    "1258291",
    "failed",
    "Reader error: file is password-protected",
    { category: "billing" },
    8000,
    "Uploaded by Sam Rivera",
  ),
  content(
    "c3",
    "refund-policy-2026.pdf",
    "PDF",
    "421888",
    "completed",
    "48 chunks",
    { category: "billing" },
    5000,
    "Uploaded by Maya Chen",
  ),
  content(
    "c4",
    "help-center articles",
    "URL",
    "",
    "completed",
    "6,410 chunks",
    { source: "web" },
    6000,
    "help.northwind.dev/sitemap.xml",
  ),
  content(
    "c5",
    "s3://northwind-kb/macros/",
    "S3",
    "",
    "completed",
    "388 chunks",
    { source: "macros" },
    7400,
    "Remote source · northwind-kb",
  ),
  content(
    "c6",
    "status-page-faq",
    "Text",
    "4096",
    "completed",
    "6 chunks",
    { category: "incidents" },
    12000,
    "Pasted text",
  ),
];

export const sampleSearchResults: AgentOS.PaginatedResponseVectorSearchResult = {
  data: [
    {
      id: "chunk_14",
      content:
        "Duplicate charges caused by a payment retry are refunded in full to the original card within 5 to 10 business days. Do not promise an exact date.",
      name: "refund-policy-2026.pdf",
      reranking_score: 0.86,
      meta_data: { chunk: 14 },
    },
    {
      id: "chunk_2",
      content:
        "Apologise, confirm the order number and both charge amounts, then request the refund through the billing tool so it can be approved.",
      name: "s3://northwind-kb/macros/refund_duplicate.md",
      reranking_score: 0.81,
      meta_data: { chunk: 2 },
    },
  ],
  meta: { page: 1, limit: 5, total_pages: 1, total_count: 2, search_time_ms: 142 },
};

export const sampleLearnings: AgentOS.LearningResponse[] = [
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
    learning_id: "user_profile_maya",
    learning_type: "user_profile",
    user_id: "maya@northwind.dev",
    agent_id: "support-triage",
    content: {
      role: "Billing ops approver",
      answer_style: "Short, with a link to the trace",
      on_call: ["Monday", "Thursday"],
    },
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
];

export const sampleLearningCounts: LearningCountsOut = {
  counts: {
    user_profile: 212,
    user_memory: 198,
    session_context: 1406,
    entity_memory: 87,
    decision_log: 634,
  },
  id_schemes: {
    user_profile: "Deterministic id: user_profile_{user_id}",
    user_memory: "Deterministic id: memories_{user_id}",
    session_context: "One record per session",
    entity_memory: "Generated id · keyed by entity_type and entity_id",
    decision_log: "Generated id · many per user",
  },
};

export const sampleFileConfig = {
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
};

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

const ENTRIES: Record<string, AgentOS.FileSystemEntry[]> = {
  "": [
    { path: "reports", type: "directory", size_bytes: 40_000, updated_at: epochAgo(60) },
    { path: "exports", type: "directory", size_bytes: 900_000, updated_at: epochAgo(600) },
    { path: "shared", type: "directory", size_bytes: 12_000, updated_at: epochAgo(9000) },
  ],
  reports: [
    { path: "reports/daily-brief", type: "directory", size_bytes: 36_000, updated_at: epochAgo(60) },
    { path: "reports/weekly-ops", type: "directory", size_bytes: 4_000, updated_at: epochAgo(3000) },
  ],
  "reports/daily-brief": [
    { path: "reports/daily-brief/2026-10-31.md", type: "file", size_bytes: 1_126, updated_at: epochAgo(60) },
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
    { path: "reports/daily-brief/index.json", type: "file", size_bytes: 2_048, updated_at: epochAgo(1500) },
  ],
};

export const sampleFileProvenance: FileProvenanceOut = {
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
};

export function contextHandlers() {
  return [
    http.get(`${GATEWAY}/config`, () =>
      HttpResponse.json({ memory: { dbs: [{ db_id: "agno-postgres" }] }, ...sampleFileConfig }),
    ),
    http.get(`${GATEWAY}/user_memory_stats`, () => HttpResponse.json(page(sampleMemoryUsers))),
    http.get(`${GATEWAY}/memories`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      const topic = params.get("topics");
      const text = params.get("search_content")?.toLowerCase();
      const items = sampleMemories.filter(
        (item) =>
          (!topic || (item.topics ?? []).includes(topic)) &&
          (!text || item.memory.toLowerCase().includes(text)),
      );
      return HttpResponse.json({
        ...page(items),
        meta: { ...page(items).meta, total_count: topic || text ? items.length : 14 },
      });
    }),
    http.get(`${GATEWAY}/memory_topics`, () =>
      HttpResponse.json([
        "billing",
        "preferences",
        "devices",
        "contact",
        "plan",
        "refunds",
        "timezone",
        "exports",
      ]),
    ),
    http.get(`${API}/instances/:instance/memories/duplicates`, () => HttpResponse.json(sampleDuplicates)),
    http.get(`${API}/instances/:instance/memories/:memory/source`, () =>
      HttpResponse.json(sampleMemorySource),
    ),
    http.post(`${API}/instances/:instance/memories/optimize`, async ({ request }) => {
      const body = (await request.json()) as { apply?: boolean };
      return HttpResponse.json({ ...sampleOptimization, applied: Boolean(body.apply) });
    }),
    http.get(`${API}/instances/:instance/knowledge/bases`, () => HttpResponse.json(sampleKnowledgeBases)),
    http.get(`${API}/instances/:instance/knowledge/content`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      const status = params.get("status");
      const rows = sampleContent.filter((row) => !status || row.status === status);
      return HttpResponse.json({
        data: rows,
        matching: rows.length,
        scanned: sampleContent.length,
        total: sampleContent.length,
        partial: false,
        counts: {
          total: sampleContent.length,
          by_status: { completed: 4, processing: 1, partial: 0, failed: 1 },
          by_kind: { Markdown: 1, DOCX: 1, PDF: 1, URL: 1, S3: 1, Text: 1 },
        },
        page: 1,
        limit: 20,
      });
    }),
    http.get(`${GATEWAY}/knowledge/config`, () =>
      HttpResponse.json({
        readers: { markdown: { id: "markdown", name: "Markdown" }, pdf: { id: "pdf", name: "PDF" } },
        chunkers: { RecursiveChunker: { key: "RecursiveChunker", name: "Recursive" } },
      }),
    ),
    http.get(`${GATEWAY}/knowledge/content/:id/status`, () =>
      HttpResponse.json({ id: "c1", status: "processing", status_message: "Embedding, 62%" }),
    ),
    http.post(`${GATEWAY}/knowledge/search`, () => HttpResponse.json(sampleSearchResults)),
    http.get(`${GATEWAY}/knowledge/:kb/sources`, () => HttpResponse.json([])),
    http.get(`${API}/instances/:instance/learnings/counts`, () => HttpResponse.json(sampleLearningCounts)),
    http.get(`${GATEWAY}/learnings`, ({ request }) => {
      const type = new URL(request.url).searchParams.get("learning_type");
      return HttpResponse.json(page(sampleLearnings.filter((item) => !type || item.learning_type === type)));
    }),
    http.post(`${API}/instances/:instance/learnings/delete-user`, async ({ request }) => {
      const body = (await request.json()) as { user_id: string; learning_type: string | null };
      return HttpResponse.json({
        instance_id: PROD,
        instance: "prod-agentos",
        user_id: body.user_id,
        learning_type: body.learning_type,
        deleted: 3,
      });
    }),
    http.post(`${API}/context/data-subject-requests`, async ({ request }) => {
      const body = (await request.json()) as { user_id: string };
      const result: DataSubjectOut = {
        user_id: body.user_id,
        outcomes: [
          { instance_id: PROD, instance: "prod-agentos", status: "deleted", deleted: 4, reason: null },
          {
            instance_id: "ins_staging",
            instance: "staging-agentos",
            status: "skipped",
            deleted: null,
            reason: "You don't have learnings:delete here.",
          },
        ],
      };
      return HttpResponse.json(result);
    }),
    http.get(`${GATEWAY}/filesystem/entries`, ({ request }) => {
      const directory = new URL(request.url).searchParams.get("directory") ?? "";
      return HttpResponse.json({
        namespace: "workspace",
        agent_ids: ["daily-brief"],
        directory,
        entries: ENTRIES[directory] ?? [],
        usage: { file_count: 312, total_bytes: 2.1 * 1024 ** 3, bytes_limit: 20 * 1024 ** 3 },
        meta: { page: 1, limit: 100, total_pages: 1, total_count: (ENTRIES[directory] ?? []).length },
      });
    }),
    http.get(`${GATEWAY}/filesystem/content`, ({ request }) => {
      const path = new URL(request.url).searchParams.get("path") ?? "";
      return HttpResponse.json({
        namespace: "workspace",
        agent_ids: ["daily-brief"],
        path,
        content: path.endsWith(".csv") ? "title,source,score\nAndroid 4.12 sync,status page,0.9\n" : BRIEF,
        size_bytes: 7_578,
        line_count: 12,
        truncated: false,
        offset: 0,
        limit: 100_000,
        updated_at: epochAgo(1500),
      });
    }),
    http.get(`${API}/instances/:instance/files/provenance`, () => HttpResponse.json(sampleFileProvenance)),
  ];
}
