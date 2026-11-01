// Generates src/agentos/types.gen.ts (types only) from the AgentOS OpenAPI the backend client is pinned to.
// Pages call AgentOS through the gateway (`gatewayFetch`); these types describe what comes back.
import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../../../backend/packages/agnostic-agentos-client/openapi/agentos-3.1.12.json",
  output: { path: "./src/agentos", clean: true },
  plugins: ["@hey-api/typescript"],
});
