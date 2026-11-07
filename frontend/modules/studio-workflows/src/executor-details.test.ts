// What a step's node shows of its agent: the model with its provider's logo, one block per toolkit or tool, each
// with the logo of the service it talks to.
import type { RegistryEntryOut } from "@agnostic/api";
import { describe, expect, it } from "vitest";

import { detailsOf } from "./executor-details";

const github = { name: "org-github", catalog: { kind: "toolkit", toolkit_key: "github", icon: null } };

describe("detailsOf", () => {
  it("groups a toolkit's functions and finds the logos", () => {
    const details = detailsOf(
      {
        model: { id: "gpt-5", provider: "OpenAI" },
        tools: [
          { name: "search_issues", toolkit: "org-github" },
          { name: "create_issue", toolkit: "org-github" },
          { name: "kb_lookup" },
        ],
      },
      (name) => (name === "org-github" ? (github as unknown as RegistryEntryOut) : undefined),
    );
    expect(details).toEqual({
      model: "gpt-5",
      modelBrand: "openai",
      tools: ["org-github", "kb_lookup"],
      looks: { "org-github": { kind: "toolkit", brand: "github" }, kb_lookup: { kind: "code" } },
    });
  });

  it("keeps a model without a known provider plain", () => {
    expect(detailsOf({ model: { id: "mock-precise", provider: "Agnostic" } })).toEqual({
      model: "mock-precise",
      tools: [],
    });
  });
});
