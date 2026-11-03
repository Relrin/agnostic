import { useConfigSchema, ComponentIndex, ConfigForm, StudioEditor } from "@agnostic/studio";
import { LoadingRows } from "@agnostic/ui";
import { useParams } from "@tanstack/react-router";

/** `/i/:instance/studio/agents`: agents stored in Studio and defined in code. */
export function AgentsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  return <ComponentIndex instance={params.instance ?? ""} kind="agent" />;
}

/** `/i/:instance/studio/agents/:id` (`?layout=form|split|code`): the agent editor. */
export function AgentEditorPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const schema = useConfigSchema("agent");
  return (
    <StudioEditor
      instance={params.instance ?? ""}
      componentId={params.componentId ?? ""}
      kind="agent"
      renderForm={(ctx) =>
        schema.isPending ? (
          <LoadingRows rows={6} label="Loading the form" />
        ) : (
          <ConfigForm
            sections={schema.sections}
            fields={schema.fields}
            ctx={ctx}
            ariaLabel="Agent configuration"
          />
        )
      }
    />
  );
}
