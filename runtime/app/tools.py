"""Tools of the sample domain. They return canned data; ``refund_customer`` needs human approval."""

from agno.approval import approval
from agno.tools import tool


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order's status."""
    return f"Order {order_id}: shipped 2 days ago, arriving tomorrow."


@tool
def search_knowledge(query: str) -> str:
    """Search the help center."""
    return f"Top help-center article for '{query}': 'Refunds and returns' (updated last week)."


@tool
def web_search(query: str) -> str:
    """Search the web (offline stub)."""
    return f"3 results for '{query}' (offline stub; no network calls are made)."


@approval
@tool
def refund_customer(customer_id: str, amount: float, reason: str) -> str:
    """Refund a customer. Blocks until a human approves."""
    return f"Refunded {amount:.2f} to {customer_id} ({reason})."


ALL_TOOLS = [lookup_order, search_knowledge, web_search, refund_customer]
