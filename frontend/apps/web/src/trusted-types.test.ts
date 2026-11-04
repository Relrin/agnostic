import { describe, expect, it, vi } from "vitest";

import { ALLOWED_HTML, installTrustedTypes, sameOriginScriptUrl } from "./trusted-types";

describe("Trusted Types policy", () => {
  it("allows script URLs from this origin and blobs only", () => {
    expect(sameOriginScriptUrl("/assets/layout-worker.js", "https://agnostic.corp")).toBe(
      "https://agnostic.corp/assets/layout-worker.js",
    );
    expect(sameOriginScriptUrl("blob:https://agnostic.corp/1234", "https://agnostic.corp")).toBe(
      "blob:https://agnostic.corp/1234",
    );
    expect(() => sameOriginScriptUrl("https://cdn.example/x.js", "https://agnostic.corp")).toThrow(TypeError);
  });

  it("registers a default policy that refuses HTML", () => {
    const createPolicy = vi.fn();
    installTrustedTypes({ createPolicy });
    const [name, rules] = createPolicy.mock.calls[0] as [string, { createHTML: (value: string) => string }];
    expect(name).toBe("default");
    expect(() => rules.createHTML("<img src=x onerror=alert(1)>")).toThrow(TypeError);
    const radix = [...ALLOWED_HTML][0] ?? "";
    expect(rules.createHTML(radix)).toBe(radix);
    expect(() => rules.createHTML(`${radix}</style><script>alert(1)</script>`)).toThrow(TypeError);
  });
});
