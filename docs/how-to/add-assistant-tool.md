# Add an assistant tool

A module lets Ask your OS read its data by contributing tools. Tools are read-only, run as the person asking, and
say which pages their data came from.

## Declare the tool

```python
# modules/billing/src/agnostic_billing/api/tools.py
from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_billing.application.invoices import Invoices
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec


class InvoiceArgs(BaseModel):
    customer_id: str = Field(description="Customer id, e.g. cus_8812")


async def list_invoices(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, InvoiceArgs)
    invoices = await (await container.get(Invoices)).for_customer(call.principal, call.instance_id, args.customer_id)
    return ToolResult(
        {"invoices": [{"id": i.id, "amount": i.amount, "status": i.status} for i in invoices]},
        [Source("invoices", f"Invoices of {args.customer_id}", f"/i/{call.instance_slug}/billing?customer={args.customer_id}")],
    )


TOOLS = (ToolSpec("list_invoices", "A customer's invoices, newest first.", list_invoices, InvoiceArgs, "billing:read"),)
```

```python
# modules/billing/src/agnostic_billing/module.py
def assistant_tools(self) -> Iterable[ToolSpec]:
    return TOOLS
```

## Rules

- **Only read.** Call your use cases or `GatewayFacade.call` with `call.principal`; never write, never elevate.
- **Act as the person.** Pass `call.principal` everywhere, so scopes and user isolation apply. Set `scope` to what
  the tool needs on the instance (or `org_scope=True` for a control-plane scope such as `audit:read`): the tool is
  only offered to people who hold it, and the answer says what they can't see.
- **Stay on the instance.** Use `call.instance_id`; tools never reach other instances.
- **Keep results small.** The model reads all of it: return the fields that answer questions, clip long text with
  `agnostic_kernel.tools.clip`, cap lists.
- **Name sensitive fields** `tool_args` (arguments a runtime passed to a tool) and `user_message` (what someone typed)
  so the org's redaction settings strip them.
- **Return sources** for the pages a person would open to check the answer; they are listed under it.
- **Raise the usual errors.** `NotFoundError`, `ForbiddenError` and `ScopeMissingError` become data the model can
  explain ("you can't see that"); anything else becomes "the tool failed".

Tool names are unique across modules. Add the tool to the read-only API test's argument list
(`tests/api/test_assistant.py::test_every_tool_only_reads`) when it has required arguments.
