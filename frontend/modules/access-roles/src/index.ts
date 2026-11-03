import { defineModule } from "@agnostic/core";
import { KeyRound } from "lucide-react";

import { RolesPage } from "./roles-page";

/** Roles & permissions: org roles, access roles as a permission matrix, and what a change does to token scopes. */
export const accessRolesModule = defineModule({
  id: "access-roles",
  scope: "org",
  routes: [{ path: "access/roles", component: RolesPage }],
  nav: [
    {
      id: "roles",
      group: "access",
      label: "Roles & permissions",
      icon: KeyRound,
      path: "access/roles",
      order: 20,
    },
  ],
  requires: { anyScope: ["org:roles:read"] },
});

export { RolesPage };
