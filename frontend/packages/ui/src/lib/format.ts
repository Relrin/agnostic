// The one number format @agnostic/ui needs on its own (counts in tabs, span durations). Pages pass everything
// else already formatted by @agnostic/core.

/** 2106 → "2,106". */
export function groupDigits(value: number): string {
  const [whole = "", fraction] = String(value).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}
