// Generates src/generated from openapi.json (written by `agnostic openapi --out`). CI regenerates and fails on
// any diff, so the committed client always matches the backend (`just api-check`).
import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "./openapi.json",
  output: { path: "./src/generated", clean: true },
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk", "@tanstack/react-query"],
});
