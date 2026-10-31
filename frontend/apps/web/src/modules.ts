// Feature modules compiled into the shell. Adding a module = adding its workspace package and one line here
// (03 §2: a static import list, so every module stays code-split and tree-shaken).
import type { ModuleManifest } from "@agnostic/core";
import { helloModule } from "@agnostic/module-hello";

export const MODULES: readonly ModuleManifest[] = [helloModule];
