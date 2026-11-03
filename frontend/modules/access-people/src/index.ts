import { defineModule } from "@agnostic/core";
import { UserPlus, Users } from "lucide-react";

import { PeoplePage } from "./people-page";

/**
 * People & groups: members with their org roles and effective access per instance (direct or through groups), bulk
 * changes, manual and SCIM-synced groups with their role bindings and approval routes, invitations, and temporary
 * access requests.
 */
export const accessPeopleModule = defineModule({
  id: "access-people",
  scope: "org",
  routes: [{ path: "access/people", component: PeoplePage }],
  nav: [
    {
      id: "people",
      group: "access",
      label: "People & groups",
      icon: Users,
      path: "access/people",
      order: 10,
    },
  ],
  commands: [
    { id: "people.invite", label: "Invite people", group: "Actions", icon: UserPlus, path: "access/people" },
  ],
  requires: { anyScope: ["org:members:read"] },
});

export { PeoplePage };
