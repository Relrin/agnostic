from agno.agent import Agent

from app.registry import models, tools

billing_agent = Agent(
    id="billing-agent",
    name="billing-agent",
    description="Handles billing questions and refunds (refunds need approval).",
    model=models.agnostic_mock,
    instructions="Resolve billing questions. Refunds always go through refund_customer, which a human approves.",
    tools=[
        tools.lookup_order,
        tools.refund_customer,
    ],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
