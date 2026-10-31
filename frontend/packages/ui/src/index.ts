// @agnostic/ui: the only place feature code gets UI primitives from (never @radix-ui directly).
export { cn } from "./lib/cn";
export * as tokens from "./lib/tokens";

export { Badge, StatusPill, badgeVariants, type BadgeProps, type StatusPillProps } from "./primitives/badge";
export { Button, buttonVariants, type ButtonProps } from "./primitives/button";
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
export { EmptyState, ErrorState, LoadingRows } from "./patterns/states";
