import { afterEach, describe, expect, it } from "vitest";

import {
  configureFormatting,
  dayGroup,
  formatCalendarDay,
  formatCount,
  formatDate,
  formatDateTime,
  formatInZone,
  formatWhen,
  formattingTimeZone,
  localTimezone,
  zoneParts,
} from "./format";

afterEach(() => {
  configureFormatting({});
});

describe("formatting", () => {
  it("defaults to day-month English and a 24-hour clock", () => {
    configureFormatting({ timeZone: "UTC" });
    expect(formatDateTime("2026-11-01T09:05:00Z")).toBe("1 Nov 2026, 09:05");
    expect(formatDate("2026-11-30T12:00:00Z", { year: false })).toBe("30 Nov");
    expect(formatDate("2026-11-30T12:00:00Z", { day: false })).toBe("Nov 2026");
    expect(formatCount(2106)).toBe("2,106");
  });

  it("follows the configured locale and time zone", () => {
    configureFormatting({ locale: "de-DE", timeZone: "Asia/Tokyo" });
    expect(formatCount(2106)).toBe("2.106");
    expect(formatDateTime("2026-11-01T20:00:00Z")).toContain("05:00");
    expect(formattingTimeZone()).toBe("Asia/Tokyo");
  });

  it("ignores an empty or unknown zone and locale", () => {
    configureFormatting({ locale: "", timeZone: "Not/AZone" });
    expect(formattingTimeZone()).toBe(localTimezone());
    expect(formatCount(1000)).toBe("1,000");
  });

  it("groups days in the shown zone", () => {
    configureFormatting({ timeZone: "America/New_York" });
    const now = new Date("2026-11-04T03:00:00Z"); // 3 Nov, 22:00 in New York
    expect(dayGroup(new Date("2026-11-03T14:00:00Z"), now)).toBe("Today");
    expect(dayGroup(new Date("2026-11-02T14:00:00Z"), now)).toBe("Yesterday");
    expect(dayGroup(new Date("2026-10-30T14:00:00Z"), now)).toBe("Previous 7 days");
    expect(dayGroup(new Date("2026-10-01T14:00:00Z"), now)).toBe("Older");
    expect(formatWhen("2026-11-03T14:00:00Z", now)).toBe("Today 09:00");
  });

  it("formats API calendar days without shifting them", () => {
    configureFormatting({ timeZone: "Pacific/Honolulu" });
    expect(formatCalendarDay("2026-11-01")).toBe("1 Nov");
    expect(formatCalendarDay("2026-11-01", { weekday: true })).toBe("Sun");
  });

  it("shows wall time in a schedule's zone", () => {
    const now = new Date("2026-11-01T10:00:00Z");
    expect(formatInZone("2026-11-01T18:00:00Z", "UTC", now)).toBe("Today 18:00");
    expect(formatInZone("2026-11-02T08:00:00Z", "UTC", now)).toBe("Tomorrow 08:00");
    expect(formatInZone("2026-11-08T03:00:00Z", "UTC", now)).toBe("Sun 8 Nov, 03:00");
    expect(zoneParts(new Date("2026-11-01T03:00:00Z"), "Unknown/Zone").hour).toBe("03");
  });
});
