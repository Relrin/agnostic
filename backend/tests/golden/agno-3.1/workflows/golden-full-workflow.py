from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import HumanReview

from app.agents import billing_agent, kb_researcher, qa_reviewer, support_triage
from app.functions import check_status, needs_escalation, send_reply
from app.registry import schemas
from app.teams import escalation_team, research_team
from app.workflows import daily_brief

answer = Loop(
    name="Answer",
    steps=[
        Step(name="Draft", agent=support_triage),
        Step(name="Review", agent=qa_reviewer),
    ],
    end_condition='last_step_content.contains("APPROVED")',
    max_iterations=4,
    forward_iteration_output=True,
    human_review=HumanReview(
        requires_iteration_review=True,
    ),
)

golden_full_workflow = Workflow(
    id="golden-full-workflow",
    name="Golden full workflow",
    description="Exercises every primitive and review option Studio edits.",
    steps=[
        Step(
            name="Classify",
            agent=support_triage,
            step_id="classify",
            max_retries=1,
            human_review=HumanReview(
                requires_user_input=True,
                user_input_message="Anything the classifier should know?",
                user_input_schema=[
                    {
                        "description": "A hint",
                        "field_type": "str",
                        "name": "note",
                    },
                ],
                timeout=3600,
                on_timeout="skip",
            ),
        ),
        Steps(
            name="Prepare",
            steps=[
                Step(name="Research", team=research_team),
                Step(name="Brief", workflow=daily_brief),
            ],
            human_review=HumanReview(
                requires_confirmation=True,
                confirmation_message="Prepare a brief?",
            ),
        ),
        Parallel(
            Step(name="Look up", agent=kb_researcher),
            Step(name="Status", executor=check_status),
            name="Gather",
        ),
        Router(
            name="Route",
            selector='input.contains("refund") ? "Refund" : "Answer"',
            choices=[
                Step(name="Refund", agent=billing_agent, skip_on_failure=True),
                answer,
            ],
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Send this answer?",
            ),
        ),
        Condition(
            name="Escalate?",
            evaluator=needs_escalation,
            steps=[
                Step(name="Escalate", team=escalation_team),
            ],
            else_steps=[
                Step(name="Reply", executor=send_reply),
            ],
            human_review=HumanReview(
                on_error="fail",
            ),
        ),
    ],
    input_schema=schemas.TriageResult,
    session_state={
        "attempts": 0,
    },
    add_workflow_history_to_steps=True,
    num_history_runs=2,
    store_events=True,
)
