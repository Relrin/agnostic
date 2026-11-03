"""Structured outputs Studio may give an agent (``output_schema``), registered by class name."""

from typing import Literal

from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    category: str = Field(description="Ticket category, e.g. billing, shipping, account")
    urgency: Literal["low", "normal", "high"]
    needs_human: bool = Field(description="Hand the ticket to a person")


class RefundRequest(BaseModel):
    customer_id: str
    amount: float = Field(gt=0)
    reason: str
    order_id: str | None = None


SCHEMAS = [TriageResult, RefundRequest]
