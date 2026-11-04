// First: every later module (and its dependencies) runs under the Trusted Types policy.
import "./trusted-types";
import "@agnostic/ui/styles.css";

import { configureApi } from "@agnostic/api";
import { DensityProvider, createQueryClient } from "@agnostic/core";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { MODULES } from "./modules";
import { buildRouter } from "./router";

configureApi();
const queryClient = createQueryClient();
const router = buildRouter(MODULES, queryClient);

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <DensityProvider>
        <RouterProvider router={router} />
      </DensityProvider>
    </QueryClientProvider>
  </StrictMode>,
);
