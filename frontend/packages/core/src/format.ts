// Formatting shared by every page: durations ("worked 3.1 s"), counts, dates and times, relative times, AgentOS
// timestamps (epoch seconds, epoch milliseconds or ISO, depending on the endpoint) and wall times in a given zone.
// Dates follow the signed-in person's locale and time zone (configureFormatting, called by the shell once `me`
// loads); without them, British English and the browser's zone. This file and costs.ts are the only places that
// build Intl formatters (an ESLint rule keeps it that way).

/** English with day-month dates and a 24-hour clock, the formats the product was designed with. */
const DEFAULT_LOCALE = "en-GB";

let locale: string = DEFAULT_LOCALE;
/** `undefined`: the browser's zone. */
let timeZone: string | undefined;
const dateFormats = new Map<string, Intl.DateTimeFormat>();
let numberFormat: Intl.NumberFormat | undefined;
let relativeFormat: Intl.RelativeTimeFormat | undefined;

function validLocale(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    return Intl.getCanonicalLocales(value)[0];
  } catch {
    return undefined;
  }
}

function validZone(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value }).format(0);
    return value;
  } catch {
    return undefined;
  }
}

/**
 * Locale and time zone for every date and number below. Empty or invalid values fall back to the defaults
 * (British English, the browser's zone). Calling it again with the same values is free.
 */
export function configureFormatting(options: {
  locale?: string | null | undefined;
  timeZone?: string | null | undefined;
}): void {
  const nextLocale = validLocale(options.locale) ?? DEFAULT_LOCALE;
  const nextZone = validZone(options.timeZone);
  if (nextLocale === locale && nextZone === timeZone) return;
  locale = nextLocale;
  timeZone = nextZone;
  dateFormats.clear();
  numberFormat = undefined;
  relativeFormat = undefined;
}

/** The time zone dates are shown in: the profile's, else the browser's. */
export function formattingTimeZone(): string {
  return timeZone ?? localTimezone();
}

function dateFormat(options: Intl.DateTimeFormatOptions, zone: string | undefined = timeZone) {
  const key = `${zone ?? ""}|${JSON.stringify(options)}`;
  let format = dateFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, { ...options, ...(zone ? { timeZone: zone } : {}) });
    dateFormats.set(key, format);
  }
  return format;
}

/** Epoch seconds, epoch milliseconds or ISO → a Date (or undefined). */
export function toDate(value: string | number | null | undefined): Date | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  if (typeof value === "number") return new Date(value > 1e11 ? value : value * 1000);
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}

type DateInput = Date | string | number | null | undefined;

function asDate(value: DateInput): Date | undefined {
  return value instanceof Date ? (Number.isNaN(value.getTime()) ? undefined : value) : toDate(value);
}

/** 380 → "380 ms", 3120 → "3.1 s", 125000 → "2m 5s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${String(Math.round(ms))} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${String(minutes)}m ${String(seconds)}s` : `${String(minutes)}m`;
}

/** 2106 → "2,106". */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  numberFormat ??= new Intl.NumberFormat(locale);
  return numberFormat.format(value);
}

/** 0.018 → "1.8%". */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "2 min ago", "yesterday", "just now". */
export function formatRelative(value: DateInput, now: Date = new Date()): string {
  const date = asDate(value);
  if (!date) return "—";
  const seconds = (date.getTime() - now.getTime()) / 1000;
  relativeFormat ??= new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size)
      return relativeFormat.format(Math.round(seconds / size), unit).replace("minutes", "min");
  }
  return "just now";
}

const TIME: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit" };

/** "09:15" (or "9:15 AM" where the locale says so). */
export function formatTime(value: DateInput): string {
  const date = asDate(value);
  return date ? dateFormat(TIME).format(date) : "—";
}

/** "1 Nov 2026" by default; `{ year: false }` → "1 Nov", `{ day: false }` → "Nov 2026". */
export function formatDate(value: DateInput, { year = true, day = true } = {}): string {
  const date = asDate(value);
  if (!date) return "—";
  return dateFormat({
    month: "short",
    ...(day ? { day: "numeric" } : {}),
    ...(year ? { year: "numeric" } : {}),
  }).format(date);
}

/** "1 Nov 2026, 09:15": a full timestamp, for "since …" and "last seen …". */
export function formatDateTime(value: DateInput): string {
  const date = asDate(value);
  return date ? dateFormat({ day: "numeric", month: "short", year: "numeric", ...TIME }).format(date) : "—";
}

/**
 * A calendar day the API sends as "2026-11-01" (no zone): "1 Nov", or "Sun" with `weekday`. Never shifted by the
 * viewer's zone.
 */
export function formatCalendarDay(iso: string, { weekday = false } = {}): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return dateFormat(weekday ? { weekday: "short" } : { day: "numeric", month: "short" }, "UTC").format(date);
}

/** Days since the epoch of a moment's calendar day in a zone (so two moments compare by day). */
function dayNumber(date: Date, zone: string | undefined): number {
  const parts = zoneParts(date, zone ?? localTimezone());
  return Date.UTC(Number(parts.year), Number(parts.monthNumber) - 1, Number(parts.day)) / 86_400_000;
}

/** "Today 10:42", "Yesterday 18:03", "28 Oct 09:15". */
export function formatWhen(value: DateInput, now: Date = new Date()): string {
  const date = asDate(value);
  if (!date) return "—";
  const time = formatTime(date);
  const day = dayGroup(date, now);
  if (day === "Today" || day === "Yesterday") return `${day} ${time}`;
  return `${formatDate(date, { year: false })} ${time}`;
}

/** Session-list date groups: "Today", "Yesterday", "Previous 7 days", "Older" (days in the shown zone). */
export function dayGroup(date: Date, now: Date = new Date()): string {
  const days = dayNumber(now, timeZone) - dayNumber(date, timeZone);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return "Previous 7 days";
  return "Older";
}

/** Bytes → "182 KB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export type ZoneParts = {
  weekday: string;
  day: string;
  month: string;
  /** "11" for November. */
  monthNumber: string;
  year: string;
  hour: string;
  minute: string;
};

const zonePartFormats = new Map<string, [Intl.DateTimeFormat, Intl.DateTimeFormat]>();

/**
 * A moment's wall-clock fields in an IANA zone ("Sun", "1", "Nov", "11", "2026", "03", "00"); an unknown zone
 * reads as UTC. Field names are English whatever the locale, since they're assembled into English sentences.
 */
export function zoneParts(date: Date, zone: string): ZoneParts {
  let formats = zonePartFormats.get(zone);
  if (!formats) {
    try {
      const options = { timeZone: zone, day: "numeric", year: "numeric", hourCycle: "h23" } as const;
      formats = [
        new Intl.DateTimeFormat("en-GB", {
          ...options,
          weekday: "short",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }),
        new Intl.DateTimeFormat("en-GB", { ...options, month: "numeric" }),
      ];
    } catch {
      if (zone === "UTC") throw new Error("This browser has no UTC time zone");
      return zoneParts(date, "UTC");
    }
    zonePartFormats.set(zone, formats);
  }
  const [named, numeric] = formats;
  const parts = named.formatToParts(date);
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? "";
  return {
    weekday: get("weekday"),
    day: get("day"),
    month: get("month"),
    monthNumber: numeric.formatToParts(date).find((part) => part.type === "month")?.value ?? "",
    year: get("year"),
    hour: get("hour"),
    minute: get("minute"),
  };
}

const dayKey = (parts: ZoneParts) => `${parts.year}-${parts.monthNumber}-${parts.day}`;

/** "Today 18:00", "Tomorrow 08:00", "Sun 1 Nov, 03:00": a moment as wall time in a zone (a schedule's). */
export function formatInZone(value: string | null | undefined, zone: string, now: Date = new Date()): string {
  const date = toDate(value);
  if (!date) return "—";
  const parts = zoneParts(date, zone);
  const time = `${parts.hour}:${parts.minute}`;
  const key = dayKey(parts);
  if (key === dayKey(zoneParts(now, zone))) return `Today ${time}`;
  if (key === dayKey(zoneParts(new Date(now.getTime() + 86_400_000), zone))) return `Tomorrow ${time}`;
  if (key === dayKey(zoneParts(new Date(now.getTime() - 86_400_000), zone))) return `Yesterday ${time}`;
  return `${parts.weekday} ${parts.day} ${parts.month}, ${time}`;
}

/** Every IANA zone the browser knows (a short list where `Intl.supportedValuesOf` is missing), `current` first. */
export function timezones(current: string): string[] {
  const fallback = [
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Asia/Kolkata",
    "Australia/Sydney",
  ];
  let zones: string[] = fallback;
  try {
    const supported = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    if (supported) zones = supported("timeZone");
  } catch {
    zones = fallback;
  }
  return [...new Set(["UTC", current, ...zones])].filter(Boolean);
}

/** The browser's time zone (the default for a new schedule, and for dates when the profile has none). */
export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
