import { defineModule } from "@agnostic/core";
import { Blocks } from "lucide-react";

import { ToolCatalogPage } from "./catalog-page";

/** The tool catalog: MCP servers and Agno toolkits approved for the organization, a team, or one builder. */
export const toolCatalogModule = defineModule({
  id: "tool-catalog",
  scope: "org",
  routes: [{ path: "access/tool-catalog", component: ToolCatalogPage }],
  nav: [
    {
      id: "tool-catalog",
      group: "access",
      label: "Tool catalog",
      icon: Blocks,
      path: "access/tool-catalog",
      order: 35,
    },
  ],
  commands: [
    {
      id: "tool-catalog.open",
      label: "Open the tool catalog",
      group: "Go to",
      keywords: ["mcp", "toolkit", "tools", "agno", "approved tools"],
      path: "access/tool-catalog",
    },
  ],
  requires: { anyScope: ["tool_catalog:read"] },
});

export { ToolCatalogPage };
