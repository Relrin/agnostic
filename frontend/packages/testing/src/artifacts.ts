// Artefact fixtures: the report writer's files in one session (Markdown, HTML, CSV, PNG), the bridge's artefact
// list, the control plane's content route and share links; plus MSW handlers for them.
import type { CreatedShareOut, ShareOut, SharedArtifactOut, SharesOut } from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { GATEWAY } from "./operate";

export const SAMPLE_ARTIFACT_SESSION = "sess_report";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function artifact(
  storage: string,
  filename: string,
  contentType: string,
  kind: string,
  size: number,
  path: string,
) {
  return {
    id: `art_${storage}`,
    storage_key: `${SAMPLE_ARTIFACT_SESSION}/${storage}`,
    session_id: SAMPLE_ARTIFACT_SESSION,
    run_id: "run_report_1",
    component_kind: "agent",
    component_id: "report-writer",
    kind,
    filename,
    title: filename,
    content_type: contentType,
    size,
    sha256: "0".repeat(64),
    path,
    source: "directory",
    producer: null,
    revision: 1,
    role: "output",
    created_at: "2026-11-08T09:30:00Z",
  };
}

export const sampleArtifacts = [
  artifact("art_report.md", "report.md", "text/markdown", "file", 412, "outputs/report.md"),
  artifact("art_summary.html", "summary.html", "text/html", "file", 690, "outputs/summary.html"),
  artifact("art_data.csv", "data.csv", "text/csv", "file", 40, "outputs/data.csv"),
  artifact("art_volume.png", "volume.png", "image/png", "image", 8, "outputs/charts/volume.png"),
];

export const sampleArtifactBodies: Record<string, { body: string | Uint8Array; type: string }> = {
  "report.md": {
    body: "# Report: support volume\n\n| Quarter | Volume |\n|---|---|\n| Q1 | 61 |\n",
    type: "text/markdown",
  },
  "summary.html": { body: "<!doctype html><h1>Summary</h1>", type: "text/html" },
  "data.csv": { body: "quarter,volume\nQ1,61\nQ2,82\n", type: "text/csv" },
  "volume.png": { body: PNG, type: "image/png" },
};

export const sampleShare: ShareOut = {
  id: "shr_1",
  instance_id: "ins_prod",
  session_id: SAMPLE_ARTIFACT_SESSION,
  storage_key: `${SAMPLE_ARTIFACT_SESSION}/art_report.md`,
  filename: "report.md",
  content_type: "text/markdown",
  size: 412,
  audience: "org",
  state: "active",
  created_by: "usr_daniel",
  created_by_name: "Daniel Okafor",
  created_at: "2026-11-08T09:35:00Z",
  expires_at: "2026-11-09T09:35:00Z",
  revoked_at: null,
  opened_count: 2,
  last_opened_at: "2026-11-08T10:00:00Z",
};

export function artifactHandlers() {
  let shares: ShareOut[] = [sampleShare];
  return [
    http.get(`${GATEWAY}/agnostic/v1/artifacts`, () =>
      HttpResponse.json({ data: sampleArtifacts, scanned_sessions: 1 }),
    ),
    http.get(`${GATEWAY}/agnostic/v1/artifacts/recent`, () =>
      HttpResponse.json({ data: sampleArtifacts, scanned_sessions: 12 }),
    ),
    http.post(`${GATEWAY}/agnostic/v1/artifacts/sync`, () =>
      HttpResponse.json({ session_id: SAMPLE_ARTIFACT_SESSION, runs_synced: 0, artifacts: 0 }),
    ),
    http.get(`${API}/instances/:instance/artifacts/:session/content/*`, ({ request }) => {
      const filename = new URL(request.url).searchParams.get("filename") ?? "";
      const found = sampleArtifactBodies[filename];
      if (!found)
        return HttpResponse.json({ code: "not_found", status: 404, title: "Not found" }, { status: 404 });
      return new HttpResponse(found.body, { headers: { "content-type": found.type } });
    }),
    http.get(`${API}/instances/:instance/artifacts/shares`, () =>
      HttpResponse.json({ data: shares, public_links: true } satisfies SharesOut),
    ),
    http.post(`${API}/instances/:instance/artifacts/shares`, async ({ request }) => {
      const body = (await request.json()) as { audience: "org" | "link"; filename: string };
      const share: ShareOut = { ...sampleShare, id: "shr_2", audience: body.audience, opened_count: 0 };
      shares = [share, ...shares];
      return HttpResponse.json(
        {
          share,
          token: "ash_sample-token-0000000000000000",
          path: "/s/ash_sample-token-0000000000000000",
        } satisfies CreatedShareOut,
        { status: 201 },
      );
    }),
    http.delete(`${API}/instances/:instance/artifacts/shares/:id`, ({ params }) => {
      shares = shares.map((share) =>
        share.id === params.id ? { ...share, state: "revoked", revoked_at: "2026-11-08T11:00:00Z" } : share,
      );
      return HttpResponse.json(shares.find((share) => share.id === params.id));
    }),
    http.get(`${API}/shares/:token`, () =>
      HttpResponse.json({
        filename: "report.md",
        content_type: "text/markdown",
        size: 412,
        audience: "org",
        shared_by: "Daniel Okafor",
        created_at: "2026-11-08T09:35:00Z",
        expires_at: "2026-11-09T09:35:00Z",
      } satisfies SharedArtifactOut),
    ),
    http.get(
      `${API}/shares/:token/content`,
      () =>
        new HttpResponse(sampleArtifactBodies["report.md"]?.body, {
          headers: { "content-type": "text/markdown" },
        }),
    ),
  ];
}
