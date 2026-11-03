// Workflow step HITL: AgentOS step requirements to the StepHitlForm request, and the answer back.
import type { HitlRequest, HitlResolution } from "@agnostic/ui";

import type { StepRequirement } from "./events";

/** What a paused step asks for, in the shape StepHitlForm renders. */
export function toHitlRequest(requirement: StepRequirement): HitlRequest {
  const output = requirement.step_output;
  return {
    stepName: requirement.step_name ?? "step",
    confirmation: requirement.requires_confirmation
      ? (requirement.confirmation_message ?? "Confirm to continue the workflow.")
      : undefined,
    userInput: requirement.requires_user_input
      ? {
          message: requirement.user_input_message ?? undefined,
          fields: (requirement.user_input_schema ?? []).map((field) => ({
            name: field.name,
            type: field.field_type ?? "str",
            description: field.description ?? undefined,
            required: field.required ?? true,
            allowedValues: field.allowed_values?.map(String),
          })),
        }
      : undefined,
    routes: requirement.requires_route_selection
      ? {
          choices: requirement.available_choices ?? [],
          multiple: requirement.allow_multiple_selections ?? false,
        }
      : undefined,
    outputReview: requirement.requires_output_review
      ? typeof output === "string"
        ? output
        : JSON.stringify(output ?? {}, null, 2)
      : undefined,
  };
}

/** Apply a HITL answer to the requirement, as AgentOS expects it back in `step_requirements`. */
export function resolveRequirement(
  requirement: StepRequirement,
  resolution: HitlResolution,
): StepRequirement {
  return {
    ...requirement,
    confirmed: resolution.confirmed,
    ...(resolution.confirmed ? {} : { rejected: true }),
    ...(resolution.userInput ? { user_input: resolution.userInput } : {}),
    ...(resolution.selected ? { selected_choices: resolution.selected } : {}),
  };
}
