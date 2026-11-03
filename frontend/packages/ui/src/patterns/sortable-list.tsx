// SortableList: a vertical list reordered by dragging a grip handle or with the keyboard (focus the grip, Space to
// pick up, arrows to move, Space to drop, Escape to cancel). Items render themselves; the list owns the order.
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { GripVertical } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { cn } from "../lib/cn";

export type SortableItemState = {
  /** The grip button; place it where the row wants it. */
  handle: ReactNode;
  index: number;
  isDragging: boolean;
};

export type SortableListProps<T> = {
  items: readonly T[];
  getId: (item: T) => string;
  /** Called with the reordered items and the move that produced them. */
  onReorder: (items: T[], move: { from: number; to: number }) => void;
  renderItem: (item: T, state: SortableItemState) => ReactNode;
  /** A short name for an item, used in the grip's label and the screen-reader announcements. */
  getLabel?: (item: T) => string;
  "aria-label": string;
  disabled?: boolean;
  className?: string;
  itemClassName?: string;
};

function translate(transform: { x: number; y: number } | null): string | undefined {
  return transform
    ? `translate3d(${String(Math.round(transform.x))}px, ${String(Math.round(transform.y))}px, 0)`
    : undefined;
}

function SortableRow({
  id,
  label,
  index,
  disabled,
  className,
  children,
}: {
  id: string;
  label: string;
  index: number;
  disabled: boolean;
  className: string | undefined;
  children: (state: SortableItemState) => ReactNode;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id, disabled });
  const style: CSSProperties = { transform: translate(transform), transition };
  const handle = (
    <button
      type="button"
      ref={setActivatorNodeRef}
      data-slot="sortable-handle"
      aria-label={`Reorder ${label}`}
      disabled={disabled}
      className="flex size-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-control text-fg-muted hover:bg-surface-hover hover:text-fg focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none active:cursor-grabbing disabled:cursor-default disabled:opacity-40"
      {...attributes}
      {...listeners}
    >
      <GripVertical className="size-4" aria-hidden />
    </button>
  );
  return (
    <li
      ref={setNodeRef}
      style={style}
      data-dragging={isDragging || undefined}
      className={cn("relative data-[dragging]:z-10 data-[dragging]:shadow-popover", className)}
    >
      {children({ handle, index, isDragging })}
    </li>
  );
}

export function SortableList<T>({
  items,
  getId,
  onReorder,
  renderItem,
  getLabel,
  disabled = false,
  className,
  itemClassName,
  "aria-label": ariaLabel,
}: SortableListProps<T>) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = items.map(getId);
  const labelOf = (id: UniqueIdentifier | undefined): string => {
    const index = ids.indexOf(String(id));
    const item = items[index];
    return item === undefined ? String(id) : (getLabel?.(item) ?? `item ${String(index + 1)}`);
  };
  const position = (id: UniqueIdentifier | undefined) =>
    `position ${String(ids.indexOf(String(id)) + 1)} of ${String(ids.length)}`;
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${labelOf(active.id)}, ${position(active.id)}.`,
    onDragOver: ({ active, over }) =>
      over
        ? `${labelOf(active.id)} moved to ${position(over.id)}.`
        : `${labelOf(active.id)} is no longer over the list.`,
    onDragEnd: ({ active, over }) =>
      over ? `${labelOf(active.id)} dropped at ${position(over.id)}.` : `${labelOf(active.id)} dropped.`,
    onDragCancel: ({ active }) =>
      `Reordering cancelled; ${labelOf(active.id)} is back at ${position(active.id)}.`,
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from === -1 || to === -1) return;
    onReorder(arrayMove([...items], from, to), { from, to });
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={onDragEnd}
      accessibility={{
        announcements,
        screenReaderInstructions: {
          draggable:
            "To reorder, press Space or Enter to pick the item up, use the arrow keys to move it, then press Space or Enter again to drop it, or Escape to cancel.",
        },
      }}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy} disabled={disabled}>
        <ul
          aria-label={ariaLabel}
          data-slot="sortable-list"
          className={cn("flex flex-col gap-1.5", className)}
        >
          {items.map((item, index) => {
            const id = ids[index] ?? String(index);
            return (
              <SortableRow
                key={id}
                id={id}
                label={getLabel?.(item) ?? `item ${String(index + 1)}`}
                index={index}
                disabled={disabled}
                className={itemClassName}
              >
                {(state) => renderItem(item, state)}
              </SortableRow>
            );
          })}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
