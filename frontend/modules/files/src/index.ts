import { defineModule } from "@agnostic/core";
import { FolderTree } from "lucide-react";

import { FilesPage } from "./files-page";

export const filesModule = defineModule({
  id: "files",
  scope: "instance",
  requires: { capabilities: ["filesystem"] },
  routes: [{ path: "files", component: FilesPage }],
  nav: [{ id: "files", group: "context", label: "File system", icon: FolderTree, path: "files", order: 40 }],
});
