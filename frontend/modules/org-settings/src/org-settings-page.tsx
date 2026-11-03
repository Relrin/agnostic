import { PageIntro, Tabs, TabsContent, TabsList, TabsTrigger } from "@agnostic/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

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
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

function isSection(value: string | undefined): value is SectionId {
  return SECTIONS.some((section) => section.id === value);
}

/** `/org/settings/:section`: how people sign in and are provisioned, and where the audit log goes. */
export function OrgSettingsPage() {
  // The app's router isn't registered for type inference in modules, so params are read loosely.
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const section: SectionId = isSection(params.section) ? params.section : "authentication";
  const navigate = useNavigate();

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Organization settings">
        Sign-in and single sign-on, directory sync, and where the audit log is kept and streamed.
      </PageIntro>
      <Tabs
        value={section}
        onValueChange={(value) => {
          void navigate({ to: "/org/settings/$section", params: { section: value } });
        }}
      >
        <TabsList aria-label="Organization settings sections" className="flex-wrap">
          {SECTIONS.map((item) => (
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
      </Tabs>
    </div>
  );
}
