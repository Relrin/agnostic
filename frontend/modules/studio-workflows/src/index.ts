import { defineModule } from "@agnostic/core";
import { ComponentIndex } from "@agnostic/studio";
import { useParams } from "@tanstack/react-router";
import { Workflow } from "lucide-react";
import { createElement } from "react";

import { WorkflowBuilderPage } from "./builder-page";

/** `/i/:instance/studio/workflows`: workflows with their live version and open drafts. */
function WorkflowsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  return createElement(ComponentIndex, { instance: params.instance ?? "", kind: "workflow" });
}

export const studioWorkflowsModule = defineModule({
  id: "studio-workflows",
  scope: "instance",
  requires: { capabilities: ["components"] },
  routes: [
    { path: "studio/workflows", component: WorkflowsPage },
    { path: "studio/workflows/$componentId", component: WorkflowBuilderPage },
  ],
  nav: [
    {
      id: "workflows",
      group: "build",
      label: "Workflows",
      icon: Workflow,
      path: "studio/workflows",
      order: 30,
    },
  ],
});

export { WorkflowBuilderPage } from "./builder-page";
export { buildGraph, layoutWorkflow } from "./layout";
export * as tree from "./tree";
