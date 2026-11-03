from agno.agent import Agent

from app.registry import models, tools

support_triage = Agent(
    id="support-triage",
    name="support-triage",
    description="Classifies incoming tickets and answers simple ones.",
    model=models.agnostic_mock,
    instructions="Triage the ticket: answer from the help center when you can, otherwise hand off. Refunds go through refund_customer, which a human approves.",
    tools=[
        tools.lookup_order,
        tools.search_knowledge,
        tools.refund_customer,
    ],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
