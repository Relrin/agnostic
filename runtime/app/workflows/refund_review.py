"""refund-review: triage, research the policy (up to two passes), then a human confirms and sets the refund."""

from agno.workflow import Loop, Step, StepInput, StepOutput, Workflow
from agno.workflow.types import HumanReview

from app.agents.kb_researcher import kb_researcher
from app.agents.support_triage import support_triage


def record_refund_decision(step_input: StepInput) -> StepOutput:
    """Turn the reviewer's input (``amount``, ``reason``) into the step's output, which they then review."""
    decision = (step_input.additional_data or {}).get("user_input") or {}
    amount = float(decision.get("amount") or 0)
    reason = decision.get("reason") or "no reason given"
    return StepOutput(content=f"Refund of {amount:.2f} approved: {reason}.")


refund_review = Workflow(
    id="refund-review",
    name="refund-review",
    description="Triages a refund request, checks the refund policy, then waits for a human to set and confirm it.",
    steps=[
        Step(name="triage", agent=support_triage),
        Loop(
            name="research",
            steps=[Step(name="policy", agent=kb_researcher)],
            max_iterations=2,
            # A help-center hit ends the loop early; otherwise kb-researcher gets a second pass.
            end_condition='last_step_content.contains("article")',
        ),
        Step(
            name="approve",
            executor=record_refund_decision,
            human_review=HumanReview(
                requires_confirmation=True,
                confirmation_message="Approve this refund?",
                requires_user_input=True,
                user_input_message="Set the refund amount and the reason.",
                user_input_schema=[
                    {"name": "amount", "field_type": "float", "description": "Amount to refund"},
                    {"name": "reason", "field_type": "str", "description": "Why the refund is granted"},
                ],
                requires_output_review=True,
                output_review_message="Check the refund decision before it is recorded.",
                # Unanswered refunds expire after a day; AgentOS applies on_timeout when the run is next continued
                # (Agnostic does that itself on instances that enforce approval expiry).
                timeout=24 * 3600,
                on_timeout="cancel",
            ),
        ),
    ],
    store_events=True,
)
