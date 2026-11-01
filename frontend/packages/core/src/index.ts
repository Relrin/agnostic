export {
  defineModule,
  moduleAvailable,
  type Capability,
  type CommandDefinition,
  type ModuleManifest,
  type ModuleRoute,
  type ModuleScope,
  type NavBadge,
  type NavEntry,
  type NavGroupId,
  type NavIcon,
  type Scope,
} from "./module";
export {
  NAV_GROUPS,
  activeNavId,
  buildNavigation,
  collectCommands,
  scopedPath,
  type CatalogEntry,
  type Navigation,
  type ResolvedNavEntry,
} from "./navigation";
export { STALE_TIME, createQueryClient, withQueryFn } from "./query";
export {
  PermissionGate,
  WhyVisible,
  decide,
  isControlPlaneScope,
  scopeSatisfies,
  useCan,
  type Can,
} from "./permissions";
export {
  ORG_ROLE_LABELS,
  findInstance,
  useInstanceHealth,
  useInstances,
  useMe,
  useMyAccess,
  useOrg,
  type HealthOut,
  type InstanceOut,
  type MeOut,
  type MyAccessOut,
  type OrgOut,
} from "./session";
