import { describe, expect, it } from "vitest";

import { niceTicks, tickLabel, visibleRange } from "./virtual";

describe("visibleRange", () => {
  it("renders only the rows in view plus overscan", () => {
    expect(visibleRange(0, 504, 36, 2_000)).toEqual([0, 22]);
    expect(visibleRange(36 * 1_000, 504, 36, 2_000)).toEqual([992, 1_022]);
    expect(visibleRange(36 * 1_995, 504, 36, 2_000)).toEqual([1_987, 2_000]);
    expect(visibleRange(0, 504, 36, 0)).toEqual([0, 0]);
  });
});

describe("niceTicks", () => {
  it("picks round steps", () => {
    expect(niceTicks(64_000)).toEqual([0, 15_000, 30_000, 45_000, 60_000]);
    expect(niceTicks(900)).toEqual([0, 200, 400, 600, 800]);
    expect(niceTicks(0)).toEqual([0]);
    expect(tickLabel(15_000)).toBe("15 s");
    expect(tickLabel(250)).toBe("250 ms");
    expect(tickLabel(120_000)).toBe("2 min");
  });
});
