import { describe, expect, it } from "vitest";

import { docsLink, resolveGuideLink } from "./docs";

describe("guide links", () => {
  it("points at the in-product help", () => {
    expect(docsLink("admin/direct-mode.md")).toEqual({ href: "/help/admin/direct-mode.md" });
    expect(docsLink("/operator.md", "Operator guide")).toEqual({
      href: "/help/operator.md",
      label: "Operator guide",
    });
  });

  it("resolves relative guide links and leaves the rest alone", () => {
    expect(resolveGuideLink("admin/install.md", "upgrades.md")).toBe("/help/admin/upgrades.md");
    expect(resolveGuideLink("admin/install.md", "../runbooks/restore-drill.md#steps")).toBe(
      "/help/runbooks/restore-drill.md#steps",
    );
    expect(resolveGuideLink("operator.md", "./builder.md")).toBe("/help/builder.md");
    expect(resolveGuideLink("operator.md", "https://agno.com/docs")).toBeUndefined();
    expect(resolveGuideLink("operator.md", "#top")).toBeUndefined();
    expect(resolveGuideLink("operator.md", "../../deploy/helm/values.yaml")).toBeUndefined();
  });
});
