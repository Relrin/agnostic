// Shared constants for test helpers: the API base URL the client and MSW handlers agree on.
import { configureApi } from "@agnostic/api";

export const API = "http://agnostic.test/api/v1";

export function configureTestApi(): void {
  configureApi({ baseUrl: "http://agnostic.test" });
}
