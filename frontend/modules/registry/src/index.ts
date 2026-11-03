import { defineModule } from "@agnostic/core";
import { Library } from "lucide-react";

import { RegistryPage } from "./registry-page";

export const registryModule = defineModule({
  id: "registry",
  scope: "instance",
  requires: { capabilities: ["registry"] },
  routes: [
    { path: "studio/registry", component: RegistryPage },
    { path: "studio/registry/$type", component: RegistryPage },
    { path: "studio/registry/$type/$name", component: RegistryPage },
  ],
  nav: [
    { id: "registry", group: "build", label: "Registry", icon: Library, path: "studio/registry", order: 40 },
  ],
});
