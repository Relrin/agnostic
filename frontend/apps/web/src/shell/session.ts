// Placeholders until identity (P01) and the instance registry (P01) exist: the prototype's sample org, user
// and instance, so the shell renders exactly as designed.
import type { Environment, SidebarOrg, SidebarUser } from "@agnostic/ui";

export const DEFAULT_INSTANCE = "dev-prod";

export const PLACEHOLDER_ORG: SidebarOrg = {
  name: "Northwind Labs",
  detail: "Enterprise · 24 seats",
  logoLetter: "N",
};

export const PLACEHOLDER_USER: SidebarUser = {
  id: "usr_dana",
  name: "Dana Okafor",
  role: "Owner",
  email: "dana@northwind.dev",
};

export const PLACEHOLDER_INSTANCES: Record<string, { name: string; env: Environment }> = {
  "dev-prod": { name: "dev-prod", env: "production" },
  "dev-staging": { name: "dev-staging", env: "staging" },
};
