// The tool catalog against a stubbed control plane: Daniel reviews the organization's and the Data team's entries,
// checks which instance runtimes pulled them, then adds catalog tools to support-triage as tool blocks and sets up
// a raw Agno toolkit for staging.
import { expect, test, type Page } from "@playwright/test";

import {
  catalogEntries,
  catalogRegistryTools,
  catalogSyncStatus,
  catalogToolkits,
} from "../../../packages/testing/src/fixtures/tool-catalog";
import { stubStudio } from "./fixtures/studio";
import { access, stubApi } from "./stubs";

const CATALOG_SCOPES = ["tool_catalog:read", "tool_catalog:write", "tool_catalog:local"];

async function stubCatalog(page: Page): Promise<{ created: unknown[] }> {
  const state: { created: unknown[] } = { created: [] };
  const withCatalog = {
    ...access,
    control_plane_scopes: [...access.control_plane_scopes, ...CATALOG_SCOPES],
  };
  await page.route(/\/api\/v1\/me\/access/, (route) => route.fulfill({ json: withCatalog }));
  await page.route(/\/api\/v1\/tool-catalog\/entries(\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      state.created.push(body);
      return route.fulfill({
        status: 201,
        json: { ...catalogEntries[4], id: "tce_new", registry_name: `custom-x7k2pq-${String(body.slug)}` },
      });
    }
    const level = new URL(route.request().url()).searchParams.get("level");
    return route.fulfill({ json: catalogEntries.filter((entry) => !level || entry.level === level) });
  });
  await page.route(/\/api\/v1\/tool-catalog\/toolkits/, (route) =>
    route.fulfill({ json: { agno_version: "3.1.12", from_instance: true, toolkits: catalogToolkits } }),
  );
  await page.route(/\/api\/v1\/tool-catalog\/instances\/[^/]+\/status$/, (route) =>
    route.fulfill({ json: catalogSyncStatus }),
  );
  await page.route(/\/api\/v1\/directory\/groups(\?.*)?$/, (route) =>
    route.fulfill({ json: [{ id: "grp_data", name: "Data", member_count: 6 }] }),
  );
  return state;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`) });
}

test("tool catalog: entries per level and what each runtime pulled", async ({ page }) => {
  await stubApi(page);
  await stubCatalog(page);
  await page.goto("/access/tool-catalog");

  const org = page.getByRole("list", { name: "org entries" });
  await expect(org.getByText("org-linear")).toBeVisible();
  await expect(org.getByText("Also offered as")).toBeVisible();
  await shot(page, "01-organization");

  await page.getByRole("tab", { name: "Teams" }).click();
  const team = page.getByRole("list", { name: "team entries" });
  await expect(team.getByText("team-data-warehouse")).toBeVisible();
  await shot(page, "02-teams");

  await page.getByRole("button", { name: "Add to the catalog" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText("Add to the tool catalog")).toBeVisible();
  await sheet.getByRole("textbox", { name: "Name", exact: true }).fill("Sentry");
  await sheet.getByRole("textbox", { name: "Server URL" }).fill("https://mcp.sentry.dev/mcp");
  await sheet.getByRole("textbox", { name: "Header 1 environment variable" }).fill("SENTRY_TOKEN");
  await shot(page, "03-add-mcp-server");
  await sheet.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("tab", { name: "Instances" }).click();
  const instances = page.getByRole("list", { name: "Instances" });
  await expect(instances.getByText("Set WAREHOUSE_KEY on the runtime.").first()).toBeVisible();
  await shot(page, "04-instances");
});

test("studio: catalog tools as blocks, and a raw toolkit set up for staging", async ({ page }) => {
  await stubApi(page);
  await stubStudio(page);
  const catalog = await stubCatalog(page);
  // The registry Studio reads, with the tool catalog's entries marked (later routes win in Playwright).
  await page.route(/\/api\/v1\/instances\/[^/]+\/studio\/registry(\?.*)?$/, (route) =>
    route.fulfill({
      json: {
        instance: "staging-agentos",
        entries: [
          ...catalogRegistryTools,
          {
            ...catalogRegistryTools[0],
            name: "kb_lookup",
            description: "Search the help center.",
            meta: "app.tools.kb.kb_lookup",
            catalog: null,
            functions: [],
            config_value: [
              { name: "kb_lookup", parameters: { type: "object", properties: {}, required: [] } },
            ],
          },
          {
            ...catalogRegistryTools[0],
            type: "model",
            name: "mock-precise",
            catalog: null,
            config_value: { id: "mock-precise", provider: "Agnostic" },
          },
        ],
        counts: { tool: catalogRegistryTools.length + 1, model: 1 },
        total: catalogRegistryTools.length + 2,
        bridge: true,
      },
    }),
  );
  await page.goto("/i/staging-agentos/studio/agents/support-triage");
  const attached = page.getByRole("list", { name: "Attached tools" });
  await expect(attached.getByText("kb_lookup").first()).toBeVisible();

  await page.getByRole("button", { name: "Add a tool" }).click();
  const picker = page.getByRole("dialog", { name: "Add a tool" });
  await expect(picker.getByRole("region", { name: "Organization" })).toBeVisible();
  await expect(picker.getByText("Organization version available")).toBeVisible();
  await shot(page, "05-tool-picker");
  await picker.getByRole("button", { name: /Linear/ }).click();
  await expect(attached.getByText("org-linear")).toBeVisible();

  await page.getByRole("button", { name: "Add a tool" }).click();
  await picker.getByRole("button", { name: /Data search/ }).click();
  await expect(attached.getByText("team-data-search")).toBeVisible();
  await attached.scrollIntoViewIfNeeded();
  await shot(page, "06-tool-blocks");

  await page.getByRole("button", { name: "Add a tool" }).click();
  await picker.getByRole("button", { name: /Tavily/ }).click();
  const setup = page.getByRole("dialog", { name: "Set up Tavily" });
  await setup.getByRole("textbox", { name: "api_key" }).fill("tavily_api_key");
  await shot(page, "07-configure-toolkit");
  await setup.getByRole("button", { name: "Set up for this instance" }).click();
  await expect(setup.getByText(/is set up/)).toBeVisible();
  expect(catalog.created).toEqual([
    expect.objectContaining({
      level: "custom",
      toolkit_key: "tavily",
      instance_ids: ["staging-agentos"],
      config: { params: { api_key: { env: "TAVILY_API_KEY" } } },
    }),
  ]);
});
