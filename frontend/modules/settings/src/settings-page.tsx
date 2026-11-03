import {
  describeError,
  instancesGetConfigOptions,
  instancesGetHealthOptions,
  instancesGetInstanceOptions,
  instancesListInstancesQueryKey,
  problemCode,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import {
  Callout,
  ErrorState,
  LoadingRows,
  PageIntro,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@agnostic/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";

import { ApprovalsSection, NotificationsSection } from "./control-sections";
import {
  AuthorizationSection,
  ConnectionSection,
  DangerZone,
  DatabasesSection,
  InterfacesSection,
  SectionJson,
} from "./sections";

export const SECTIONS = [
  { id: "connection", label: "Connection" },
  { id: "authorization", label: "Authorization" },
  { id: "databases", label: "Databases" },
  { id: "interfaces", label: "Interfaces" },
  { id: "tracing", label: "Tracing" },
  { id: "queue", label: "Queue" },
  { id: "approvals", label: "Approvals" },
  { id: "notifications", label: "Notifications" },
  { id: "danger", label: "Danger zone" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

function isSection(value: string | undefined): value is SectionId {
  return SECTIONS.some((section) => section.id === value);
}

/** `/i/:instance/settings/:section`: the instance's connection, trust and the runtime's real `/config`. */
export function SettingsPage() {
  // The app's router isn't registered for type inference in modules, so params are read loosely.
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const ref = params.instance ?? "";
  const section: SectionId = isSection(params.section) ? params.section : "connection";
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const instance = useQuery(withQueryFn(instancesGetInstanceOptions({ path: { instance: ref } })));
  const health = useQuery(withQueryFn(instancesGetHealthOptions({ path: { instance: ref } })));
  const config = useQuery({
    ...withQueryFn(instancesGetConfigOptions({ path: { instance: ref } })),
    enabled: ["databases", "interfaces", "tracing", "queue"].includes(section),
    retry: false,
  });

  if (instance.isPending) {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-8 pt-6">
        <LoadingRows rows={6} label="Loading settings" />
      </div>
    );
  }
  if (instance.isError) {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-8 pt-6">
        <ErrorState reason={describeError(instance.error).reason} onRetry={() => void instance.refetch()} />
      </div>
    );
  }

  const configBody = () => {
    if (config.isPending) return <LoadingRows rows={4} label="Loading /config" />;
    if (config.isError) {
      const tone = problemCode(config.error) === "scope_missing" ? "availability" : "danger";
      return <Callout tone={tone}>{describeError(config.error).reason}</Callout>;
    }
    if (!config.data.fetched_at) {
      return (
        <Callout tone="availability">
          No /config snapshot yet. Run Test connection on the Connection tab.
        </Callout>
      );
    }
    switch (section) {
      case "databases":
        return <DatabasesSection instance={instance.data} config={config.data} />;
      case "interfaces":
        return <InterfacesSection config={config.data} />;
      case "tracing":
        return (
          <SectionJson
            title="Tracing"
            value={config.data.sections.traces}
            empty="Tracing is off: pass tracing=True to AgentOS. Traces can contain prompts and tool arguments; viewing them needs traces:read."
          />
        );
      default:
        return (
          <SectionJson
            title="Queue"
            value={config.data.sections.queue}
            empty="No queue section: runs execute in-process. QueueConfig(durable=True) adds a durable queue."
          />
        );
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title={`Settings · ${instance.data.display_name}`}>
        Connection, trust and what the runtime reports in /config.
        {config.data?.fetched_at
          ? ` Snapshot from ${new Date(config.data.fetched_at).toLocaleString()}.`
          : ""}
      </PageIntro>
      <Tabs
        value={section}
        onValueChange={(value) => {
          void navigate({ to: "/i/$instance/settings/$section", params: { instance: ref, section: value } });
        }}
      >
        <TabsList aria-label="Settings sections" className="flex-wrap">
          {SECTIONS.map((item) => (
            <TabsTrigger key={item.id} value={item.id}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="connection" className="pt-5">
          <ConnectionSection instance={instance.data} capabilities={health.data?.capabilities ?? []} />
        </TabsContent>
        <TabsContent value="authorization" className="pt-5">
          <AuthorizationSection instance={instance.data} />
        </TabsContent>
        {(["databases", "interfaces", "tracing", "queue"] as const).map((id) => (
          <TabsContent key={id} value={id} className="pt-5">
            {section === id && configBody()}
          </TabsContent>
        ))}
        <TabsContent value="approvals" className="pt-5">
          {section === "approvals" && <ApprovalsSection instance={instance.data} />}
        </TabsContent>
        <TabsContent value="notifications" className="pt-5">
          {section === "notifications" && <NotificationsSection />}
        </TabsContent>
        <TabsContent value="danger" className="pt-5">
          <DangerZone
            instance={instance.data}
            onDeleted={() => {
              void queryClient.invalidateQueries({ queryKey: instancesListInstancesQueryKey() });
              void navigate({ to: "/instances" });
            }}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
