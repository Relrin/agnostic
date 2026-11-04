// Sticky notes on the canvas. They live in the draft's canvas layout next to the manual offsets
// (`{positions, notes}`), never in the workflow config: agno and the generated code don't see them.
export type Note = { id: string; x: number; y: number; width: number; text: string };

export type Offsets = Record<string, { x: number; y: number }>;

/** What the canvas layout stores for a draft. */
export type CanvasState = { positions: Offsets; notes: Note[] };

export const NOTE_PREFIX = "note:";
export const NOTE_WIDTH = 240;

function isNote(value: unknown): value is Note {
  if (typeof value !== "object" || value === null) return false;
  const note = value as Record<string, unknown>;
  return (
    typeof note.id === "string" &&
    typeof note.x === "number" &&
    typeof note.y === "number" &&
    typeof note.text === "string"
  );
}

/** The stored layout, tolerating older shapes (positions only) and anything malformed. */
export function readCanvasState(layout: unknown): CanvasState {
  const value = typeof layout === "object" && layout !== null ? (layout as Record<string, unknown>) : {};
  const positions =
    typeof value.positions === "object" && value.positions !== null ? (value.positions as Offsets) : {};
  const notes = Array.isArray(value.notes)
    ? value.notes.filter(isNote).map((note) => ({ ...note, width: note.width || NOTE_WIDTH }))
    : [];
  return { positions, notes };
}

export function newNote(x: number, y: number, text = ""): Note {
  const id = `${NOTE_PREFIX}${Math.random().toString(36).slice(2, 10)}`;
  return { id, x, y, width: NOTE_WIDTH, text };
}
