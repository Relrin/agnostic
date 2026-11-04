// Token values mirrored for TypeScript: the Storybook "Tokens" page and the automated contrast test read them.
// Keep in sync with styles/tokens.css (the contrast test fails if a pair drops below its threshold).

export const surfaces = {
  "--bg": "#0B0C0E",
  "--bg-canvas": "#0D0F11",
  "--bg-rail": "#0E1012",
  "--bg-inset": "#0F1113",
  "--surface": "#121417",
  "--surface-raised": "#15171A",
  "--surface-selected": "#17191C",
  "--row-selected": "#171A1E",
  "--surface-hover": "#1A1D22",
  "--track": "#1C1F24",
  "--bubble-user": "#1E2228",
  "--segment-active": "#262A31",
} as const;

export const lines = {
  "--divider-row": "#1A1D21",
  "--border-subtle": "#1F2227",
  "--border": "#23272D",
  "--border-input": "#2A2E35",
  "--border-strong": "#2E333A",
  "--border-dashed": "#3A3F47",
} as const;

export const text = {
  "--fg-active": "#F1F2F4",
  "--fg": "#ECEDEF",
  "--fg-prose": "#D6D9DE",
  "--fg-secondary": "#A9AFB8",
  "--fg-muted": "#8A919B",
  "--fg-faint": "#7D848E",
  "--fg-disabled": "#6B727C",
  "--fg-line-number": "#5F6670",
  "--neutral-mark": "#5B6472",
} as const;

export const accents = {
  "--accent": "#C5F25C",
  "--warning": "#F2B54B",
  "--danger": "#FF8A80",
  "--info": "#9DBBFF",
  "--modified": "#7DA6FF",
} as const;

export const entities = {
  "--entity-agent": "#7DA6FF",
  "--entity-team": "#B79CFF",
  "--entity-workflow": "#59D4E8",
  "--entity-fn": "#A9AFB8",
  "--node-condition": "#F2B54B",
  "--node-loop": "#F28FC0",
  "--note": "#221D12",
  "--note-border": "#4A3D1E",
  "--note-fg": "#F5DFA8",
  "--reg-schema": "#F2A0C0",
  "--reg-function": "#8FE0D0",
  "--reg-knowledge": "#E8C27A",
  "--reg-model": "#C5F25C",
  "--chart-1": "#3987E5",
  "--chart-2": "#D95926",
  "--chart-3": "#199E70",
} as const;

export const avatarPalette = [
  ["#2B3A55", "#CFE0FF"],
  ["#3A2F55", "#E1D6FF"],
  ["#4A3A22", "#FFE2B0"],
  ["#22443A", "#C8F5E2"],
  ["#4A2236", "#FFD0E4"],
  ["#23404A", "#CDEFFA"],
  ["#3B3F22", "#ECF2C2"],
] as const;

/** Text/background pairs that must meet WCAG contrast. `min` is the required ratio. */
export const contrastPairs = [
  { fg: "--fg", bg: "--bg", min: 4.5 },
  { fg: "--fg-secondary", bg: "--bg", min: 4.5 },
  { fg: "--fg-secondary", bg: "--surface", min: 4.5 },
  { fg: "--fg-muted", bg: "--bg", min: 4.5 },
  { fg: "--fg-muted", bg: "--surface", min: 4.5 },
  { fg: "--fg-faint", bg: "--bg", min: 4.5 },
  { fg: "--fg-faint", bg: "--surface", min: 4.5 },
  { fg: "--accent", bg: "--bg", min: 4.5 },
  { fg: "--warning", bg: "--bg", min: 4.5 },
  { fg: "--danger", bg: "--bg", min: 4.5 },
  { fg: "--info", bg: "--bg", min: 4.5 },
  { fg: "--bg", bg: "--accent", min: 4.5 },
  { fg: "--note-fg", bg: "--note", min: 4.5 },
] as const;

export const allColors: Record<string, string> = { ...surfaces, ...lines, ...text, ...accents, ...entities };

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}
