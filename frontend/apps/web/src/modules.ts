// Feature modules compiled into the shell. Adding a module = adding its workspace package and one line here
// (03 §2: a static import list, so every module stays code-split and tree-shaken).
import type { ModuleManifest } from "@agnostic/core";
import { accessPeopleModule } from "@agnostic/module-access-people";
import { accessRolesModule } from "@agnostic/module-access-roles";
import { accountModule } from "@agnostic/module-account";
import { approvalsModule } from "@agnostic/module-approvals";
import { assistantModule } from "@agnostic/module-assistant";
import { auditModule } from "@agnostic/module-audit";
import { chatModule } from "@agnostic/module-chat";
import { evalsModule } from "@agnostic/module-evals";
import { filesModule } from "@agnostic/module-files";
import { helpModule } from "@agnostic/module-help";
import { homeModule } from "@agnostic/module-home";
import { identityModule } from "@agnostic/module-identity";
import { instancesModule } from "@agnostic/module-instances";
import { knowledgeModule } from "@agnostic/module-knowledge";
import { learningsModule } from "@agnostic/module-learnings";
import { memoryModule } from "@agnostic/module-memory";
import { metricsModule } from "@agnostic/module-metrics";
import { orgSettingsModule } from "@agnostic/module-org-settings";
import { queueModule } from "@agnostic/module-queue";
import { registryModule } from "@agnostic/module-registry";
import { schedulerModule } from "@agnostic/module-scheduler";
import { serviceAccountsModule } from "@agnostic/module-service-accounts";
import { sessionsModule } from "@agnostic/module-sessions";
import { settingsModule } from "@agnostic/module-settings";
import { sourcesModule } from "@agnostic/module-sources";
import { studioAgentsModule } from "@agnostic/module-studio-agents";
import { studioTeamsModule } from "@agnostic/module-studio-teams";
import { studioWorkflowsModule } from "@agnostic/module-studio-workflows";
import { systemModule } from "@agnostic/module-system";
import { tracesModule } from "@agnostic/module-traces";

export const MODULES: readonly ModuleManifest[] = [
  identityModule,
  accountModule,
  instancesModule,
  settingsModule,
  orgSettingsModule,
  systemModule,
  helpModule,
  accessPeopleModule,
  accessRolesModule,
  serviceAccountsModule,
  auditModule,
  homeModule,
  chatModule,
  studioAgentsModule,
  studioTeamsModule,
  studioWorkflowsModule,
  registryModule,
  sourcesModule,
  sessionsModule,
  tracesModule,
  metricsModule,
  evalsModule,
  memoryModule,
  knowledgeModule,
  learningsModule,
  filesModule,
  approvalsModule,
  schedulerModule,
  queueModule,
  assistantModule,
];
