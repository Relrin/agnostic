// @agnostic/studio: the building blocks of the Studio editors (agents, teams, workflows).
export { CodePane, pathAtLine, spanLines } from "./code-pane";
export { ComponentIndex } from "./component-index";
export {
  TEAM_MODES,
  changedFields,
  display,
  instructions,
  isRecord,
  memberId,
  members,
  modelId,
  pinsFrom,
  refName,
  teamMode,
  tools,
  withField,
  type Config,
  type EditableKind,
  type MemberEntry,
  type TeamMode,
  type ToolEntry,
} from "./config";
export { ConflictDialog, DiffDialog, PromoteDialog, PublishDialog, VersionsDrawer } from "./dialogs";
export {
  useComponent,
  useConfigSchema,
  useDebouncedValue,
  useDraftDocument,
  useRegistry,
  type CodeState,
  type DraftDocument,
  type FieldInfo,
  type SourceCode,
  type SaveState,
  type Section,
} from "./document";
export { DraftChip, FAMILY_LABEL, StudioEditor, unpublished, type Layout } from "./editor";
export { ConfigForm, FieldControl, RawConfigEditor, fieldId, type FormContext } from "./form";
export { MODE_BLURB, MODE_LABEL, flowSteps, sectionSummary } from "./summaries";
export { TestPane, checkStructured } from "./test-pane";
