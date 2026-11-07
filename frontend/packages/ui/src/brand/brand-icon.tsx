// A brand logo, in the brand's own colors or the current text color, and the tool and model marks built on it: the
// logo when the brand is known, a generic glyph (by kind or toolkit category) when it isn't. Logos are decorative next to the tool's name;
// `title` makes one stand alone.
import {
  Briefcase,
  Calculator,
  ChartColumn,
  Code2,
  Database,
  FileText,
  Globe,
  Image,
  Mail,
  MessageSquare,
  Search,
  Sheet,
  Sparkles,
  SquareTerminal,
  Timer,
  TrendingUp,
  Webhook,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { useId } from "react";

import { cn } from "../lib/cn";
import { modelBrand, toolBrand, type ToolBrandInput } from "./brands";
import { BRAND_GLYPHS, type BrandId } from "./glyphs.gen";

/** `color`: the brand's own colors (parts too dark for the theme use the text color); `mono`: the text color. */
export type BrandTone = "color" | "mono";

export function BrandIcon({
  brand,
  tone = "color",
  className,
  title,
}: {
  brand: BrandId;
  tone?: BrandTone | undefined;
  className?: string | undefined;
  /** Accessible name; without it the logo is hidden from assistive technology. */
  title?: string | undefined;
}) {
  // Gradient ids are per instance: a logo shown twice (or hidden in a closed panel) never borrows another's.
  const prefix = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const glyph = BRAND_GLYPHS[brand];
  const color = tone === "color" ? glyph.color : undefined;
  const paths = color?.paths ?? glyph.paths;
  const fill = (value: string | undefined) =>
    value?.replace(/^url\(#(g\d+)\)$/, `url(#${prefix}-$1)`) ?? color?.fill;
  return (
    <svg
      viewBox={glyph.viewBox}
      fill="currentColor"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      data-brand={brand}
      data-tone={color ? "color" : "mono"}
      className={cn("size-3.5 shrink-0", className)}
    >
      {paths.map(({ mixBlendMode, fill: own, ...path }, index) => (
        <path key={index} {...path} fill={fill(own)} style={mixBlendMode ? { mixBlendMode } : undefined} />
      ))}
      {color?.gradients && color.gradients.length > 0 && (
        <defs>
          {color.gradients.map(({ stops, ...gradient }, index) => (
            <linearGradient key={index} id={`${prefix}-g${String(index)}`} {...gradient}>
              {stops.map((stop, at) => (
                <stop key={at} {...stop} />
              ))}
            </linearGradient>
          ))}
        </defs>
      )}
    </svg>
  );
}

/** Generic glyphs for toolkits without a brand: by toolkit, then by the toolkit list's category. */
const TOOLKIT_GLYPHS: Readonly<Record<string, LucideIcon>> = {
  calculator: Calculator,
  chart: ChartColumn,
  code_mode: SquareTerminal,
  coding: SquareTerminal,
  csv: Sheet,
  custom_api: Webhook,
  email: Mail,
  file: FileText,
  file_generation: FileText,
  finance: TrendingUp,
  local_file_system: FileText,
  sleep: Timer,
  sql: Database,
  visualization: ChartColumn,
  web_search: Search,
  y_finance: TrendingUp,
};

const CATEGORY_GLYPHS: Readonly<Record<string, LucideIcon>> = {
  search: Search,
  web: Globe,
  social: MessageSquare,
  data: Database,
  productivity: Briefcase,
  media: Image,
  local: SquareTerminal,
};

export type ToolMarkProps = Omit<ToolBrandInput, "kind"> & {
  /** Where the tool comes from: "mcp", "toolkit", or "code" (registered in the runtime's code). */
  kind?: "mcp" | "toolkit" | "code" | undefined;
  /** The toolkit list's category, for a toolkit without a logo. */
  category?: string | undefined;
  className?: string | undefined;
};

/** The mark of a tool: its brand's logo, or a generic glyph for what it is. */
export function ToolMark({ kind, category, className, ...brandInput }: ToolMarkProps) {
  const brand = toolBrand({ ...brandInput, kind: kind === "code" ? undefined : kind });
  if (brand) return <BrandIcon brand={brand} className={className} />;
  const Icon =
    kind === "mcp"
      ? undefined
      : ((brandInput.toolkitKey ? TOOLKIT_GLYPHS[brandInput.toolkitKey] : undefined) ??
        (category ? CATEGORY_GLYPHS[category] : undefined) ??
        (kind === "toolkit" ? Wrench : Code2));
  // An MCP server without a brand shows the protocol's own mark.
  if (!Icon) return <BrandIcon brand="mcp" className={className} />;
  return <Icon aria-hidden className={cn("size-3.5 shrink-0", className)} />;
}

/** The mark of a model: its provider's logo, or a generic one. */
export function ModelMark({
  provider,
  id,
  className,
}: {
  provider?: string | null | undefined;
  id?: string | null | undefined;
  className?: string | undefined;
}) {
  const brand = modelBrand({ provider, id });
  if (brand) return <BrandIcon brand={brand} className={className} />;
  return <Sparkles aria-hidden className={cn("size-3.5 shrink-0", className)} />;
}
