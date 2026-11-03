from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import HumanReview

from app.agents import kb_researcher, support_triage
from app.functions import record_refund_decision

refund_review = Workflow(
    id="refund-review",
    name="refund-review",
    description="Triages a refund request, checks the refund policy, then waits for a human to set and confirm it.",
    steps=[
        Step(name="triage", agent=support_triage),
        Loop(
            name="research",
            steps=[
                Step(name="policy", agent=kb_researcher),
            ],
            end_condition='last_step_content.contains("article")',
            max_iterations=2,
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
                    {
                        "description": "Amount to refund",
                        "field_type": "float",
                        "name": "amount",
                    },
                    {
                        "description": "Why the refund is granted",
                        "field_type": "str",
                        "name": "reason",
                    },
                ],
                requires_output_review=True,
                output_review_message="Check the refund decision before it is recorded.",
                timeout=86400,
            ),
        ),
    ],
    store_events=True,
)
