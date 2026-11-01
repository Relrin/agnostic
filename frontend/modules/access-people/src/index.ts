import { defineModule } from "@agnostic/core";
import { UserPlus, Users } from "lucide-react";

import { PeoplePage } from "./people-page";

/** People (basic, P01): members, org roles, direct role bindings, invitations. Groups and SCIM arrive in P06. */
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
