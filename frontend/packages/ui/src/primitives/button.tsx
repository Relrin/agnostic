import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

export const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-button text-[13px] font-medium whitespace-nowrap transition-colors duration-[var(--motion-fast)] ease-out disabled:pointer-events-none disabled:text-fg-disabled [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent font-semibold text-accent-fg hover:brightness-105 disabled:bg-surface-hover",
        secondary: "border border-border-strong bg-surface text-fg hover:bg-surface-hover",
        outline: "border border-border-strong bg-transparent text-fg hover:bg-surface",
        subtle: "bg-surface-hover text-fg hover:bg-segment-active",
        ghost: "bg-transparent text-fg-secondary hover:bg-surface-hover hover:text-fg",
        icon: "bg-transparent text-fg-secondary hover:bg-surface-hover hover:text-fg",
        "dashed-add":
          "border border-dashed border-border-dashed bg-transparent text-fg-secondary hover:text-fg",
        "destructive-text": "bg-transparent text-danger hover:bg-danger/10",
        "destructive-outline": "border border-danger/45 bg-transparent text-danger hover:bg-danger/10",
        link: "h-auto bg-transparent px-0 text-info hover:text-info-hover hover:underline",
      },
      size: {
        "36": "h-[var(--control-h-36)] px-4",
        "34": "h-[var(--control-h-34)] px-3.5",
        "32": "h-[var(--control-h-32)] rounded-control px-3",
        "30": "h-[var(--control-h-30)] rounded-control px-2.5 text-[12.5px]",
        "28": "h-[var(--control-h-28)] rounded-control px-2 text-[12.5px]",
      },
    },
    compoundVariants: [
      { variant: "icon", size: "36", className: "w-[var(--control-h-36)] px-0" },
      { variant: "icon", size: "34", className: "w-[var(--control-h-34)] px-0" },
      { variant: "icon", size: "32", className: "w-[var(--control-h-32)] px-0" },
      { variant: "icon", size: "30", className: "w-[var(--control-h-30)] px-0" },
      { variant: "icon", size: "28", className: "w-[var(--control-h-28)] px-0" },
    ],
    defaultVariants: { variant: "secondary", size: "34" },
  },
);

export type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    /** Render the child element (e.g. a router link) with button styles. */
    asChild?: boolean;
  };

export function Button({ className, variant, size, asChild = false, type, ...props }: ButtonProps) {
  const Component = asChild ? Slot.Root : "button";
  return (
    <Component
      data-slot="button"
      type={asChild ? undefined : (type ?? "button")}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
