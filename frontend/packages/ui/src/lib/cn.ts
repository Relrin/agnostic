import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge our custom radius and colour scales so conflicting classes resolve correctly.
const merge = extendTailwindMerge({
  extend: {
    theme: {
      radius: ["type", "bar", "badge", "control", "button", "segment", "tile", "radio", "card", "panel"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return merge(clsx(inputs));
}
