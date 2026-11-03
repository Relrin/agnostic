// One-line natural-language summaries of form sections (shown while a section is collapsed) and the team flow
// explainer, written from the actual config: member names, knowledge, the iteration cap.
import {
  count,
  flag,
  instructions,
  memberId,
  members,
  modelId,
  refName,
  teamMode,
  text,
  tools,
  type Config,
  type TeamMode,
} from "./config";

const ADVANCED = [
  "system_message",
  "retries",
  "dependencies",
  "metadata",
  "tool_choice",
  "store_events",
  "stream",
  "debug_mode",
];

function plural(value: number, noun: string): string {
  return `${String(value)} ${noun}${value === 1 ? "" : "s"}`;
}

export function sectionSummary(section: string, config: Config): string {
  switch (section) {
    case "identity":
      return text(config, "id") ?? text(config, "name") ?? "not named yet";
    case "model": {
      const model = modelId(config.model);
      const reasoning = modelId(config.reasoning_model);
      if (!model) return "instance default";
      return reasoning ? `${model} · reasoning ${reasoning}` : model;
    }
    case "instructions": {
      const items = instructions(config).length;
      return items ? plural(items, "instruction") : "none";
    }
    case "tools": {
      const items = tools(config);
      if (!items.length) return "none";
      const approvals = items.filter(
        (tool) => tool.requires_confirmation === true || Boolean(tool.approval_type),
      ).length;
      return approvals
        ? `${plural(items.length, "tool")} · ${String(approvals)} need approval`
        : plural(items.length, "tool");
    }
    case "knowledge": {
      const name = refName(config.knowledge);
      if (!name) return "none";
      return `${name} · search ${flag(config, "search_knowledge", true) ? "on" : "off"}`;
    }
    case "memory": {
      if (config.learning === true || refName(config.learning))
        return `learning ${refName(config.learning) ?? "on"}`;
      if (flag(config, "enable_agentic_memory")) return "agentic memory on";
      if (flag(config, "update_memory_on_run")) return "memories after every run";
      return "off";
    }
    case "context": {
      const summaries = flag(config, "enable_session_summaries") ? "summaries on" : "summaries off";
      if (!flag(config, "add_history_to_context")) return `history off · ${summaries}`;
      return `${plural(count(config, "num_history_runs") ?? 3, "run")} · ${summaries}`;
    }
    case "output": {
      const schema = config.output_schema;
      if (typeof schema === "string") return schema;
      if (schema) return "inline JSON Schema";
      return flag(config, "markdown") ? "Markdown" : "none";
    }
    case "session_state":
      return config.session_state ? "on" : "off";
    case "team":
      return MODE_LABEL[teamMode(config)];
    case "members": {
      const items = members(config).length;
      return items ? plural(items, "member") : "no members yet";
    }
    case "advanced": {
      const set = ADVANCED.filter((key) => config[key] !== undefined).length;
      return set ? `${plural(set, "setting")} set` : "defaults";
    }
    default:
      return "";
  }
}

export const MODE_LABEL: Record<TeamMode, string> = {
  coordinate: "Coordinate",
  route: "Route",
  broadcast: "Broadcast",
  tasks: "Tasks",
};

export const MODE_BLURB: Record<TeamMode, string> = {
  coordinate: "Leader picks members, writes their tasks, and combines the results.",
  route: "Leader hands the request to one member and returns its answer as-is.",
  broadcast: "Every member gets the same task; the leader merges the answers.",
  tasks: "Leader keeps a shared task list and loops until done or the iteration cap.",
};

function names(list: string[]): string {
  if (list.length <= 1) return list[0] ?? "the members";
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1] ?? ""}`;
}

/** The numbered walkthrough of how a request flows through the team in its mode. */
export function flowSteps(config: Config): string[] {
  const ids = members(config).map(memberId).filter(Boolean);
  const knowledge = refName(config.knowledge);
  const writes = flag(config, "determine_input_for_members", true);
  const input = writes
    ? "writes a task for each member it picks"
    : "passes the user message to the members it picks";
  switch (teamMode(config)) {
    case "coordinate":
      return [
        `The leader splits the question and ${input}.`,
        `${names(ids)} work on their parts${knowledge ? `; the leader can search ${knowledge}` : ""}.`,
        "The leader merges their answers into one response.",
      ];
    case "route":
      return [
        `The leader reads the request and picks the one member best suited to it (${names(ids)}).`,
        "That member's answer goes back to the user unchanged. There is no synthesis step.",
      ];
    case "broadcast":
      return [
        `${ids.length === 1 ? "The member receives" : `All ${String(ids.length)} members receive`} the same task. Async runs execute them concurrently.`,
        `The leader combines the ${ids.length === 1 ? "answer" : `${String(ids.length)} answers`} into one response.`,
      ];
    case "tasks": {
      const cap = count(config, "max_iterations") ?? 10;
      return [
        "The leader writes a shared task list for the goal.",
        `Members take tasks (${names(ids)}); the leader updates the list after each one.`,
        `The loop ends when the goal is met or after ${plural(cap, "iteration")}.`,
      ];
    }
  }
}
