// Display density: the app root provides it (from the signed-in person's preference) and sets the matching
// `data-density` attribute on <html> for the CSS side (tokens.css). Components with fixed JS sizes read it here.
import { createContext, useContext } from "react";

export type Density = "comfortable" | "compact";

export const DENSITIES: readonly Density[] = ["comfortable", "compact"];

export const DensityContext = createContext<Density>("comfortable");

/** The density in effect; "comfortable" outside a provider (tests, Storybook without the toolbar). */
export function useDensityContext(): Density {
  return useContext(DensityContext);
}
