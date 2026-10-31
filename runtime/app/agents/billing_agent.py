"""Billing agent: Handles billing questions and refunds (refunds need approval)."""

from agno.agent import Agent

from app.models.mock import MockModel
from app.tools import lookup_order, refund_customer

billing_agent = Agent(
    id="billing-agent",
    name="billing-agent",
    description="Handles billing questions and refunds (refunds need approval).",
    model=MockModel(persona="billing-agent"),
    tools=[lookup_order, refund_customer],
    instructions="Resolve billing questions. Refunds always go through refund_customer, which a human approves.",
    markdown=True,
)
