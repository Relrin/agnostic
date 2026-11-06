// MSW handlers for the tool catalog: entries by level, the toolkit list, per-instance sync status and a sync token.
import type { EntryIn, EntryOut } from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { catalogEntries, catalogSyncStatus, catalogToolkits } from "./fixtures/tool-catalog";

export {
  catalogEntries,
  catalogRegistryTools,
  catalogSyncStatus,
  catalogToolkits,
} from "./fixtures/tool-catalog";

export function toolCatalogHandlers(store: { created: EntryIn[] } = { created: [] }) {
  return [
    http.get(`${API}/tool-catalog/entries`, ({ request }) => {
      const url = new URL(request.url);
      const level = url.searchParams.get("level");
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      return HttpResponse.json(
        catalogEntries.filter(
          (entry) =>
            (!level || entry.level === level) &&
            (!q || `${entry.display_name} ${entry.registry_name}`.toLowerCase().includes(q)),
        ),
      );
    }),
    http.post(`${API}/tool-catalog/entries`, async ({ request }) => {
      const body = (await request.json()) as EntryIn;
      store.created.push(body);
      const [template] = catalogEntries;
      if (!template) throw new Error("the fixtures have catalog entries");
      const created: EntryOut = {
        ...template,
        id: "tce_new",
        slug: body.slug,
        registry_name: `${body.level}-${body.slug}`,
        level: body.level,
        display_name: body.display_name,
        kind: body.kind,
        toolkit_key: body.toolkit_key ?? null,
        config: body.config ?? {},
      };
      return HttpResponse.json(created, { status: 201 });
    }),
    http.get(`${API}/tool-catalog/toolkits`, () =>
      HttpResponse.json({ agno_version: "3.1.12", from_instance: true, toolkits: catalogToolkits }),
    ),
    http.get(`${API}/tool-catalog/instances/:instance/status`, ({ params }) =>
      HttpResponse.json({ ...catalogSyncStatus, instance_id: String(params.instance) }),
    ),
    http.post(`${API}/tool-catalog/instances/:instance/sync`, () => HttpResponse.json({ reached: true })),
  ];
}
