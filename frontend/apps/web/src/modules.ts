// Feature modules compiled into the shell. Adding a module = adding its workspace package and one line here
// (03 §2: a static import list, so every module stays code-split and tree-shaken).
import type { ModuleManifest } from "@agnostic/core";
import { accessPeopleModule } from "@agnostic/module-access-people";
import { accountModule } from "@agnostic/module-account";
import { auditModule } from "@agnostic/module-audit";
import { identityModule } from "@agnostic/module-identity";
import { instancesModule } from "@agnostic/module-instances";
import { settingsModule } from "@agnostic/module-settings";

export const MODULES: readonly ModuleManifest[] = [
  identityModule,
  accountModule,
  instancesModule,
  settingsModule,
  accessPeopleModule,
  auditModule,
];
