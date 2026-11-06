import { describe, expect, it } from "vitest";

import { formFrom, gitlabIssuer, providerBody, withPreset } from "./authentication-section";

describe("provider form", () => {
  it("drops the old preset's URLs when the preset changes", () => {
    const github = { ...formFrom(undefined), preset: "github" as const, baseUrl: "https://ghe.corp.test" };
    const gitlab = withPreset(github, "gitlab");
    expect(gitlab.baseUrl).toBe("");
    expect(providerBody(gitlab)).toMatchObject({ preset: "gitlab", base_url: null });
    expect(withPreset(gitlab, "gitlab")).toBe(gitlab);
  });

  it("sends the instance URL for GitLab and GitHub Enterprise", () => {
    const form = {
      ...formFrom(undefined),
      preset: "gitlab" as const,
      baseUrl: " https://gitlab.corp.test/ ",
    };
    expect(providerBody(form)).toMatchObject({ base_url: "https://gitlab.corp.test/" });
    expect(providerBody(form)).not.toHaveProperty("issuer");
    expect(providerBody({ ...form, preset: "github" })).toMatchObject({
      base_url: "https://gitlab.corp.test/",
    });
  });

  it("shows which issuer GitLab sign-in uses", () => {
    expect(gitlabIssuer("")).toBe("https://gitlab.com");
    expect(gitlabIssuer("https://gitlab.corp.test//")).toBe("https://gitlab.corp.test");
  });
});
