import { API, helloHandlers, renderWithProviders } from "@agnostic/testing";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { HelloPage } from "./hello-page";

const server = setupServer(...helloHandlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...helloHandlers());
});
afterAll(() => {
  server.close();
});

describe("HelloPage", () => {
  it("lists greetings with their status and reply", async () => {
    renderWithProviders(<HelloPage />);
    expect(await screen.findByText("Hi from Dana")).toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("Reply queued · the worker is on it")).toBeInTheDocument();
  });

  it("creates a greeting and shows it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelloPage />);
    await user.type(await screen.findByLabelText("Greeting"), "Ship it");
    await user.click(screen.getByRole("button", { name: "Send greeting" }));
    expect(await screen.findByText("Ship it")).toBeInTheDocument();
    expect(screen.getByLabelText("Greeting")).toHaveValue("");
  });

  it("shows the empty state", async () => {
    server.use(http.get(`${API}/hello/greetings`, () => HttpResponse.json({ data: [], next_cursor: null })));
    renderWithProviders(<HelloPage />);
    expect(await screen.findByText("No greetings yet")).toBeInTheDocument();
  });

  it("shows the problem detail and request id on errors", async () => {
    server.use(
      http.get(`${API}/hello/greetings`, () =>
        HttpResponse.json(
          {
            type: "urn:agnostic:problem:unavailable",
            title: "A dependency is unavailable",
            status: 503,
            code: "unavailable",
            detail: "Database is down.",
            request_id: "req_1",
          },
          { status: 503 },
        ),
      ),
    );
    renderWithProviders(<HelloPage />);
    await waitFor(
      () => {
        expect(screen.getByRole("alert")).toHaveTextContent("Database is down.");
      },
      { timeout: 5000 },
    );
    expect(screen.getByText("Request id req_1")).toBeInTheDocument();
  });
});
