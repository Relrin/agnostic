import { describe, expect, it } from "vitest";

import { resolveArtifactPath, viewerKind } from "./api";

describe("resolveArtifactPath", () => {
  it("resolves a link against the folder of the file it is in", () => {
    expect(resolveArtifactPath("outputs/report.md", "charts/volume.svg")).toBe("outputs/charts/volume.svg");
    expect(resolveArtifactPath("outputs/report.md", "./charts/volume.svg")).toBe("outputs/charts/volume.svg");
    expect(resolveArtifactPath("outputs/deep/report.md", "../chart.png")).toBe("outputs/chart.png");
    expect(resolveArtifactPath("report.md", "chart.png")).toBe("chart.png");
  });

  it("reads a leading slash as the workspace root and ignores query and fragment", () => {
    expect(resolveArtifactPath("outputs/report.md", "/charts/a.png?v=2#top")).toBe("charts/a.png");
  });

  it("decodes escaped names", () => {
    expect(resolveArtifactPath("outputs/report.md", "my%20chart.png")).toBe("outputs/my chart.png");
    expect(resolveArtifactPath("outputs/report.md", "100%.png")).toBe("outputs/100%.png");
  });

  it("leaves URLs, fragments and paths above the root alone", () => {
    expect(resolveArtifactPath("outputs/report.md", "https://example.com/a.png")).toBeUndefined();
    expect(resolveArtifactPath("outputs/report.md", "data:image/png;base64,AAAA")).toBeUndefined();
    expect(resolveArtifactPath("outputs/report.md", "//cdn.example.com/a.png")).toBeUndefined();
    expect(resolveArtifactPath("outputs/report.md", "#section")).toBeUndefined();
    expect(resolveArtifactPath("outputs/report.md", "../../etc/passwd")).toBeUndefined();
  });
});

describe("viewerKind", () => {
  it("shows Jupyter notebooks as notebooks, not JSON", () => {
    expect(viewerKind("application/x-ipynb+json", "analysis.ipynb")).toBe("notebook");
    expect(viewerKind("application/json", "analysis.ipynb")).toBe("notebook");
    expect(viewerKind("application/octet-stream", "Analysis.IPYNB")).toBe("notebook");
    expect(viewerKind("application/json", "data.json")).toBe("json");
  });
});
