// Arranging nodes by hand on the canvas: group frames that grow around the steps moved inside them, aligning and
// distributing the picked nodes, the grid they can snap to, and what a selection rectangle catches. Everything
// here works on plain boxes in canvas coordinates, so the canvas decides where the boxes come from.
import { GROUP_FOOTER, GROUP_HEADER } from "@agnostic/ui";
import type { CoordinateExtent, XYPosition } from "@xyflow/react";

import type { FlowNode } from "./nodes";

/** The grid nodes snap to when snapping is on; the canvas background draws its dots on it. */
export const GRID = 22;

/** Room a group frame keeps around its steps (as the layout pads it). */
const FRAME_PADDING = { right: 24, bottom: 22 };

/** Where a step can go inside its group: anywhere below the frame's header; the frame grows to the right and down. */
export const CHILD_EXTENT: CoordinateExtent = [
  [8, GROUP_HEADER + 4],
  [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY],
];

export type Box = { id: string; x: number; y: number; width: number; height: number };

export type Alignment = "left" | "center" | "right" | "top" | "middle" | "bottom";
export type Axis = "horizontal" | "vertical";

/** How far each box moves. */
export type Moves = Map<string, XYPosition>;

/**
 * Group frames grown to hold their steps wherever they were moved: a frame is never smaller than its layout, and
 * nested frames grow first so the frames around them make room for them too.
 */
export function fitGroups(nodes: FlowNode[]): FlowNode[] {
  const kids = new Map<string, number[]>();
  nodes.forEach((node, index) => {
    if (node.parentId) kids.set(node.parentId, [...(kids.get(node.parentId) ?? []), index]);
  });
  if (kids.size === 0) return nodes;
  const fitted = [...nodes];
  // Children come after their parents, so walking backwards sizes the innermost frames first.
  for (let index = fitted.length - 1; index >= 0; index -= 1) {
    const frame = fitted[index];
    if (frame?.type !== "frame") continue;
    let width = frame.width ?? 0;
    let height = frame.height ?? 0;
    const bottom = FRAME_PADDING.bottom + (frame.data.footer ? GROUP_FOOTER : 0);
    for (const at of kids.get(frame.id) ?? []) {
      const child = fitted[at];
      if (!child) continue;
      width = Math.max(width, child.position.x + (child.width ?? 0) + FRAME_PADDING.right);
      height = Math.max(height, child.position.y + (child.height ?? 0) + bottom);
    }
    if (width !== frame.width || height !== frame.height) fitted[index] = { ...frame, width, height };
  }
  return fitted;
}

/** Line the boxes up on one edge (or centre) of the area they cover together. */
export function align(boxes: readonly Box[], alignment: Alignment): Moves {
  const moves: Moves = new Map();
  if (boxes.length < 2) return moves;
  const left = Math.min(...boxes.map((box) => box.x));
  const right = Math.max(...boxes.map((box) => box.x + box.width));
  const top = Math.min(...boxes.map((box) => box.y));
  const bottom = Math.max(...boxes.map((box) => box.y + box.height));
  for (const box of boxes) {
    const dx = {
      left: left - box.x,
      center: (left + right) / 2 - (box.x + box.width / 2),
      right: right - (box.x + box.width),
      top: 0,
      middle: 0,
      bottom: 0,
    }[alignment];
    const dy = {
      left: 0,
      center: 0,
      right: 0,
      top: top - box.y,
      middle: (top + bottom) / 2 - (box.y + box.height / 2),
      bottom: bottom - (box.y + box.height),
    }[alignment];
    if (dx !== 0 || dy !== 0) moves.set(box.id, { x: dx, y: dy });
  }
  return moves;
}

/** Even gaps between the boxes along an axis; the first and the last stay where they are. */
export function distribute(boxes: readonly Box[], axis: Axis): Moves {
  const moves: Moves = new Map();
  if (boxes.length < 3) return moves;
  const start = (box: Box) => (axis === "horizontal" ? box.x : box.y);
  const size = (box: Box) => (axis === "horizontal" ? box.width : box.height);
  const sorted = [...boxes].sort((a, b) => start(a) - start(b));
  const first = sorted[0];
  const last = sorted.at(-1);
  if (!first || !last) return moves;
  const span = start(last) + size(last) - start(first);
  const gap = (span - sorted.reduce((total, box) => total + size(box), 0)) / (sorted.length - 1);
  let cursor = start(first);
  for (const box of sorted) {
    const delta = cursor - start(box);
    if (delta !== 0) moves.set(box.id, axis === "horizontal" ? { x: delta, y: 0 } : { x: 0, y: delta });
    cursor += size(box) + gap;
  }
  return moves;
}

/** Each box's top-left corner moved to the nearest grid point. */
export function toGrid(boxes: readonly Box[], grid = GRID): Moves {
  const moves: Moves = new Map();
  for (const box of boxes) {
    const dx = Math.round(box.x / grid) * grid - box.x;
    const dy = Math.round(box.y / grid) * grid - box.y;
    if (dx !== 0 || dy !== 0) moves.set(box.id, { x: dx, y: dy });
  }
  return moves;
}

/** A rectangle from two corners in any order. */
export function rectBetween(a: XYPosition, b: XYPosition): Omit<Box, "id"> {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  };
}

/** Whether a selection rectangle catches a box: touching it is enough, unless `whole` asks for all of it. */
export function caught(box: Box, rect: Omit<Box, "id">, whole: boolean): boolean {
  if (whole) {
    return (
      box.x >= rect.x &&
      box.y >= rect.y &&
      box.x + box.width <= rect.x + rect.width &&
      box.y + box.height <= rect.y + rect.height
    );
  }
  return (
    box.x < rect.x + rect.width &&
    box.x + box.width > rect.x &&
    box.y < rect.y + rect.height &&
    box.y + box.height > rect.y
  );
}
