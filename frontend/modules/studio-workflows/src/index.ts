import { defineModule } from "@agnostic/core";
import { ComponentIndex } from "@agnostic/studio";
import { useParams } from "@tanstack/react-router";
import { Workflow } from "lucide-react";
import { createElement } from "react";

/** `/i/:instance/studio/workflows`: workflows with their live version and open drafts. */
function WorkflowsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  return createElement(ComponentIndex, { instance: params.instance ?? "", kind: "workflow" });
}

export const studioWorkflowsModule = defineModule({
  id: "studio-workflows",
  scope: "instance",
  requires: { capabilities: ["components"] },
  routes: [{ path: "studio/workflows", component: WorkflowsPage }],
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
