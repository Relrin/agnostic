// A connection between two ports: a curve in its port type's colour, brighter when it touches the selected node or
// carries the test run, with a "+" in the middle that inserts a step there (click it, or drop a palette item or a
// step's grip on it).
import { InsertButton, PORT_TYPES, type PortType } from "@agnostic/ui";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";

import { useBuilderContext } from "./context";
import { useBuilder } from "./history";
import { useDropOn } from "./nodes";
import type { Slot } from "./tree";

export type FlowEdgeData = {
  port: PortType;
  slot?: Slot | undefined;
  /** The run has gone along this connection (both ends ran, or the target is running). */
  lit: boolean;
};
export type FlowEdgeType = Edge<FlowEdgeData, "flow">;

/** Whether a connection touches the selected node. */
function touches(selected: string | undefined, source: string, target: string): boolean {
  if (!selected) return false;
  return source === selected || target === selected;
}

export function FlowEdge(props: EdgeProps<FlowEdgeType>) {
  const { store, actions, readOnly } = useBuilderContext();
  const near = useBuilder(store, (state) => touches(state.selected, props.source, props.target));
  const [path, labelX, labelY] = getBezierPath({ ...props, curvature: 0.35 });
  const slot = props.data?.slot;
  const drop = useDropOn(slot);
  const color = PORT_TYPES[props.data?.port ?? "message"].color;
  const strong = near || props.data?.lit === true;
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        style={{ stroke: color, strokeWidth: near ? 2.5 : 2, strokeOpacity: strong ? 1 : 0.55 }}
      />
      {slot && !readOnly && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute"
            style={{
              transform: `translate(-50%, -50%) translate(${String(labelX)}px, ${String(labelY)}px)`,
              pointerEvents: "all",
            }}
          >
            <InsertButton
              onInsert={() => {
                actions.add(slot, "Step");
              }}
              onDropItem={drop}
            />
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const EDGE_VIEWS = { flow: FlowEdge };
