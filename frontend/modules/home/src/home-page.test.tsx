import { API, p01Handlers, p02Handlers, renderPage, sampleOverview } from "@agnostic/testing";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { HomePage, kpiDelta } from "./home-page";

const handlers = () => [...p01Handlers(), ...p02Handlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

describe("HomePage", () => {
  it("shows what needs attention, the KPIs and the primitives", async () => {
    renderPage(HomePage, { path: "/i/$instance/home", url: "/i/prod-agentos/home" });
    expect(await screen.findByText("3 approvals waiting")).toBeInTheDocument();
    expect(screen.getByText("daily-brief failed twice")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/approvals?tool=refund_customer",
    );
    expect(screen.getByText("6 agents · 3 agent teams · 5 workflows on prod-agentos")).toBeInTheDocument();

    const kpis = screen.getByRole("region", { name: "Key metrics, last 7 days" });
    expect(within(kpis).getByText("4,912")).toBeInTheDocument();
    expect(within(kpis).getByText("1.8%")).toBeInTheDocument();
    expect(within(kpis).getByText("6.4 s")).toBeInTheDocument();

    const primitives = screen.getByRole("table", { name: "Primitives" });
    expect(within(primitives).getByText("support-triage")).toBeInTheDocument();
    expect(within(primitives).getByText("+ v4 draft", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Maya Chen approved refund_customer on billing-agent")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Why did daily-brief fail last night?")).toBeDisabled();
    expect(screen.getByText("Available when AI features are enabled.")).toBeInTheDocument();
  });

  it("explains sections the viewer can't see and calm instances", async () => {
    server.use(
      http.get(`${API}/instances/:instance/overview`, () =>
        HttpResponse.json({
          ...sampleOverview,
          attention: [],
          activity: null,
          unavailable: { activity: "You don't have audit:read." },
        }),
      ),
    );
    renderPage(HomePage, { path: "/i/$instance/home", url: "/i/prod-agentos/home" });
    expect(await screen.findByText(/Nothing needs you right now/)).toBeInTheDocument();
    expect(screen.getByText("You don't have audit:read.")).toBeInTheDocument();
  });

  it("shows an error state with the request id", async () => {
    server.use(
      http.get(`${API}/instances/:instance/overview`, () =>
        HttpResponse.json(
          {
            type: "x",
            title: "Down",
            status: 502,
            code: "instance_unreachable",
            detail: "prod-agentos didn't answer",
            request_id: "req_1",
          },
          { status: 502 },
        ),
      ),
    );
    renderPage(HomePage, { path: "/i/$instance/home", url: "/i/prod-agentos/home" });
    expect(await screen.findByText("prod-agentos didn't answer")).toBeInTheDocument();
    expect(screen.getByText("Request id req_1")).toBeInTheDocument();
  });
});

describe("kpiDelta", () => {
  it("colours by good and bad, not by arrow direction", () => {
    expect(
      kpiDelta({ value: 10, previous: 8, delta: 2, delta_pct: 25 }, "count", " vs previous 7 days"),
    ).toEqual({
      label: "25%",
      direction: "up",
      sentiment: "good",
      context: " vs previous 7 days",
    });
    expect(
      kpiDelta({ value: 0.018, previous: 0.014, delta: 0.004, delta_pct: 28 }, "rate", ""),
    ).toMatchObject({
      label: "0.4 pt",
      sentiment: "bad",
    });
    expect(
      kpiDelta({ value: 6400, previous: 7200, delta: -800, delta_pct: -11 }, "latency", ""),
    ).toMatchObject({
      label: "800 ms",
      direction: "down",
      sentiment: "good",
    });
    expect(kpiDelta({ value: 1, previous: null, delta: null, delta_pct: null }, "count", "")).toBeUndefined();
  });
});
