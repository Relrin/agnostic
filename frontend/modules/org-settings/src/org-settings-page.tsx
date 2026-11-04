import { useModuleEnabled } from "@agnostic/core";
import { PageIntro, Tabs, TabsContent, TabsList, TabsTrigger } from "@agnostic/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

import { AiFeaturesSection } from "./ai-features-section";
import { AuthenticationSection } from "./authentication-section";
import { DirectorySection } from "./directory-section";
import { RetentionSection } from "./retention-section";
import { SiemSection } from "./siem-section";
import { TemporaryAccessSection } from "./temporary-access-section";

export const SECTIONS = [
  { id: "authentication", label: "Authentication" },
  { id: "directory", label: "Directory sync" },
  { id: "audit-retention", label: "Audit retention & archive" },
  { id: "siem", label: "SIEM streaming" },
  { id: "temporary-access", label: "Temporary access" },
  { id: "ai-features", label: "AI features" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/** Sections of modules that are turned off don't show (AI features need the assistant module). */
const NEEDS_MODULE: Partial<Record<SectionId, string>> = { "ai-features": "assistant" };

function isSection(value: string | undefined, shown: readonly { id: SectionId }[]): value is SectionId {
  return shown.some((section) => section.id === value);
}

/** `/org/settings/:section`: how people sign in and are provisioned, and where the audit log goes. */
export function OrgSettingsPage() {
  // The app's router isn't registered for type inference in modules, so params are read loosely.
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const assistantModule = useModuleEnabled("assistant");
  const shown = SECTIONS.filter((item) => NEEDS_MODULE[item.id] !== "assistant" || assistantModule === true);
  const section: SectionId = isSection(params.section, shown) ? params.section : "authentication";
  const navigate = useNavigate();

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Organization settings">
        Sign-in and single sign-on, directory sync, where the audit log is kept and streamed, and AI features.
      </PageIntro>
      <Tabs
        value={section}
        onValueChange={(value) => {
          void navigate({ to: "/org/settings/$section", params: { section: value } });
        }}
      >
        <TabsList aria-label="Organization settings sections" className="flex-wrap">
          {shown.map((item) => (
            <TabsTrigger key={item.id} value={item.id}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="authentication" className="pt-5">
          {section === "authentication" && <AuthenticationSection />}
        </TabsContent>
        <TabsContent value="directory" className="pt-5">
          {section === "directory" && <DirectorySection />}
        </TabsContent>
        <TabsContent value="audit-retention" className="pt-5">
          {section === "audit-retention" && <RetentionSection />}
        </TabsContent>
        <TabsContent value="siem" className="pt-5">
          {section === "siem" && <SiemSection />}
        </TabsContent>
        <TabsContent value="temporary-access" className="pt-5">
          {section === "temporary-access" && <TemporaryAccessSection />}
        </TabsContent>
        <TabsContent value="ai-features" className="pt-5">
          {section === "ai-features" && <AiFeaturesSection />}
        </TabsContent>
      </Tabs>
    </div>
  );
}
