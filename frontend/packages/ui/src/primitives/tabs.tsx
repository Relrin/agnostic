import { Tabs as TabsPrimitive } from "radix-ui";
import { createContext, use, type ComponentProps } from "react";

import { cn } from "../lib/cn";

type TabsVariant = "underline" | "pill";
const VariantContext = createContext<TabsVariant>("underline");

export function Tabs({ className, ...props }: ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn("flex flex-col gap-3", className)} {...props} />;
}

export function TabsList({
  className,
  variant = "underline",
  ...props
}: ComponentProps<typeof TabsPrimitive.List> & { variant?: TabsVariant }) {
  return (
    <VariantContext value={variant}>
      <TabsPrimitive.List
        data-slot="tabs-list"
        className={cn(
          "flex items-center",
          variant === "underline" ? "gap-5 border-b border-border-subtle" : "gap-1.5",
          className,
        )}
        {...props}
      />
    </VariantContext>
  );
}

export function TabsTrigger({
  className,
  count,
  countTone = "muted",
  children,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger> & {
  count?: number;
  countTone?: "muted" | "warning" | "danger";
}) {
  const variant = use(VariantContext);
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "inline-flex cursor-pointer items-center gap-1.5 text-[13px] text-fg-secondary transition-colors hover:text-fg disabled:text-fg-disabled",
        variant === "underline"
          ? "-mb-px h-9 border-b-2 border-transparent data-[state=active]:border-accent data-[state=active]:text-fg"
          : "h-[30px] rounded-full border border-transparent px-3 data-[state=active]:border-border-dashed data-[state=active]:bg-surface-hover data-[state=active]:text-fg",
        className,
      )}
      {...props}
    >
      {children}
      {count !== undefined && (
        <span
          className={cn(
            "tabular rounded-full px-1.5 font-mono text-[10.5px] leading-4",
            countTone === "warning" && "bg-warning/14 text-warning",
            countTone === "danger" && "bg-danger/12 text-danger",
            countTone === "muted" && "bg-surface-hover text-fg-muted",
          )}
        >
          {count.toLocaleString("en-US")}
        </span>
      )}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content data-slot="tabs-content" className={cn("outline-none", className)} {...props} />
  );
}
