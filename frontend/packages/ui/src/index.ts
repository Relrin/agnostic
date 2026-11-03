// @agnostic/ui: the only place feature code gets UI primitives from (never @radix-ui directly).
export { cn } from "./lib/cn";
export * as tokens from "./lib/tokens";

export { Badge, StatusPill, badgeVariants, type BadgeProps, type StatusPillProps } from "./primitives/badge";
export { Button, buttonVariants, type ButtonProps } from "./primitives/button";
export { Checkbox, type CheckboxProps } from "./primitives/checkbox";
export { Combobox, type ComboboxOption, type ComboboxProps } from "./primitives/combobox";
export {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "./primitives/command";
export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./primitives/dialog";
export {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./primitives/dropdown-menu";
export { Field, RadioCards, Switch, Textarea, type RadioCardOption } from "./primitives/form";
export { Input, type InputProps } from "./primitives/input";
export {
  SegmentedControl,
  type SegmentedControlProps,
  type SegmentedOption,
} from "./primitives/segmented-control";
export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./primitives/select";
export {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "./primitives/sheet";
export {
  Sidebar,
  SidebarBadge,
  SidebarGroupLabel,
  SidebarItemContent,
  SidebarSeparator,
  navItemClassName,
  type NavBadge,
  type NavIcon,
} from "./primitives/sidebar";
export {
  Avatar,
  Breadcrumb,
  Callout,
  Kbd,
  Skeleton,
  avatarColorIndex,
  initials,
  type AvatarProps,
  type CalloutProps,
  type Crumb,
} from "./primitives/small";
export { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "./primitives/popover";
export { Tabs, TabsContent, TabsList, TabsTrigger } from "./primitives/tabs";
export { Tooltip, TooltipContent, TooltipProvider } from "./primitives/tooltip";

export { AppShell } from "./patterns/app-shell";
export {
  AppSidebar,
  OrgBadge,
  type AppSidebarGroup,
  type AppSidebarItem,
  type AppSidebarProps,
  type SidebarOrg,
  type SidebarUser,
} from "./patterns/app-sidebar";
export {
  EnvBadge,
  HealthIndicator,
  InstanceSwitcher,
  PageHeader,
  PageIntro,
  type Environment,
  type Health,
} from "./patterns/page-header";
export { CodeBlock, StepList, type StepState } from "./patterns/code-block";
export { Accordion, AccordionSection, type AccordionSectionProps } from "./patterns/accordion";
export { SortableList, type SortableItemState, type SortableListProps } from "./patterns/sortable-list";
export { EmptyState, ErrorState, LoadingRows } from "./patterns/states";
export {
  ApiHint,
  AttentionCard,
  Card,
  DataTable,
  FilterChip,
  KeyValueList,
  KpiTile,
  Pager,
  Provenance,
  type Column,
  type KpiDelta,
} from "./patterns/data";
export { JsonEditor, JsonView, MarkdownView, Toaster, toast } from "./patterns/content";
export {
  ArgsDiff,
  CRON_FIELDS,
  Countdown,
  CronFields,
  SlotBar,
  Timeline,
  formatCountdown,
  type TimelineItem,
  type TimelineState,
} from "./patterns/control";
export { ShareList, StackedBarChart, ThinBar, type BarSeries } from "./patterns/chart";
export { AccessChip, SaveBar, ScopeDiff, type DiffLine } from "./patterns/access";
export {
  ApprovalCard,
  EntitySquare,
  RunBlock,
  RunCard,
  RunTimelineSeparator,
  RunToolbar,
  StepHitlForm,
  StepTimeline,
  ToolCallChip,
  UserBubble,
  type EntityKind,
  type HitlField,
  type HitlRequest,
  type HitlResolution,
  type StepView,
  type ToolChipStatus,
} from "./domain/run";
export { GateResultList, LineLinkBadge, type GateResultRow, type GateState } from "./domain/studio";
export {
  BranchLabel,
  InsertButton,
  NODE_COLORS,
  NodeCard,
  PaletteItem,
  WorkflowGlyph,
  type BranchTone,
  type NodeCardProps,
  type WorkflowNodeStatus,
  type WorkflowNodeType,
} from "./domain/workflow";
export { Composer, SessionList, type AttachmentRule, type SessionListItem } from "./domain/chat";
export {
  SpanAttributes,
  SpanTree,
  SpanWaterfall,
  type GhostBar,
  type SpanKindName,
  type SpanRowView,
} from "./domain/trace";
export { niceTicks, tickLabel, visibleRange } from "./lib/virtual";
