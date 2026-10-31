export {
  defineModule,
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
export { STALE_TIME, createQueryClient } from "./query";
