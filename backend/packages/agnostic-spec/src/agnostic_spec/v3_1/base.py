"""What agents and teams share: identity, model, prompt, tools, knowledge, memory, history, session state."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from agnostic_spec.fields import meta_field, omitted_defaults
from agnostic_spec.v3_1.refs import KnowledgeRef, MemoryManagerRef, ModelRef, ToolRef

Kind = Literal["agent", "team", "workflow"]


class ComponentConfig(BaseModel):
    """A config document in Agno's ``to_dict()`` shape. Unknown keys (newer agno) are kept as they are."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kind: ClassVar[Kind]

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        return cls.model_validate(data)

    def dump(self) -> dict[str, Any]:
        """Only what agno would write: absent and ``None`` fields dropped, agno's omitted defaults dropped."""
        data = self.model_dump(mode="json", exclude_unset=True, by_alias=True)
        data = {key: value for key, value in data.items() if value is not None}
        for name, default in omitted_defaults(type(self)).items():
            if name in data and data[name] == default:
                del data[name]
        return data


class SharedConfig(ComponentConfig):
    # ---------------------------------------------------------------- identity
    id: str | None = meta_field("identity", "ID", help="Stable id used in API paths and links.", order=1)
    name: str | None = meta_field("identity", "Name", order=2)
    description: str | None = meta_field("identity", "Description", widget="textarea", order=3)
    role: str | None = meta_field("identity", "Role", help="How a team leader introduces this member.", order=4)
    markdown: bool | None = meta_field("output", "Format answers as Markdown", widget="switch", default=False, order=10)
    metadata: dict[str, Any] | None = meta_field("advanced", "Metadata", widget="json", order=90)

    # ---------------------------------------------------------------- model
    model: ModelRef | str | None = meta_field(
        "model",
        "Model",
        help="A model registered on the instance. Parameters such as temperature come from the preset.",
        widget="model",
        order=1,
    )
    reasoning_model: ModelRef | str | None = meta_field("model", "Reasoning model", widget="model", order=2)

    # ---------------------------------------------------------------- prompt
    instructions: list[str] | str | None = meta_field("instructions", "Instructions", widget="string_list", order=1)
    expected_output: str | None = meta_field("instructions", "Expected output", widget="textarea", order=2)
    additional_context: str | None = meta_field("instructions", "Additional context", widget="textarea", order=3)
    system_message: str | None = meta_field(
        "advanced", "System message", help="Replaces the generated system message.", widget="textarea", order=10
    )
    add_name_to_context: bool | None = meta_field(
        "instructions", "Add the name to the context", widget="switch", default=False, order=10
    )
    add_datetime_to_context: bool | None = meta_field(
        "instructions", "Add the date and time", widget="switch", default=False, order=11
    )
    add_location_to_context: bool | None = meta_field(
        "instructions", "Add the location", widget="switch", default=False, order=12
    )
    timezone_identifier: str | None = meta_field("instructions", "Time zone", order=13)
    datetime_format: str | None = meta_field("advanced", "Date and time format", order=14)

    # ---------------------------------------------------------------- tools
    tools: list[ToolRef | dict[str, Any]] | None = meta_field("tools", "Tools", widget="tools", order=1)
    tool_call_limit: int | None = meta_field("tools", "Tool call limit", widget="number", order=2)
    tool_choice: str | dict[str, Any] | None = meta_field("advanced", "Tool choice", widget="json", order=20)

    # ---------------------------------------------------------------- knowledge
    knowledge: KnowledgeRef | None = meta_field("knowledge", "Knowledge base", widget="knowledge", order=1)
    search_knowledge: bool | None = meta_field(
        "knowledge", "Search the knowledge base", widget="switch", default=True, order=2
    )
    add_knowledge_to_context: bool | None = meta_field(
        "knowledge", "Add references to the context", widget="switch", default=False, order=3
    )
    knowledge_filters: dict[str, Any] | None = meta_field("knowledge", "Filters", widget="json", order=4)
    enable_agentic_knowledge_filters: bool | None = meta_field(
        "knowledge", "Let the model choose filters", widget="switch", default=False, order=5
    )
    update_knowledge: bool | None = meta_field(
        "knowledge", "Allow adding to the knowledge base", widget="switch", default=False, order=6
    )
    references_format: Literal["json", "yaml"] | None = meta_field(
        "knowledge", "References format", widget="select", default="json", order=7
    )

    # ---------------------------------------------------------------- memory & learning
    memory_manager: MemoryManagerRef | None = meta_field("memory", "Memory manager", widget="memory_manager", order=1)
    enable_agentic_memory: bool | None = meta_field(
        "memory", "Agentic memory", help="The model decides what to remember.", widget="switch", default=False, order=2
    )
    update_memory_on_run: bool | None = meta_field(
        "memory", "Update memories after every run", widget="switch", default=False, order=3
    )
    add_memories_to_context: bool | None = meta_field("memory", "Add memories to the context", widget="switch", order=4)
    learning: bool | dict[str, Any] | None = meta_field(
        "memory",
        "Learning",
        help="A learning machine from the registry. It supersedes the memory flags above when both are set.",
        widget="learning",
        order=5,
    )
    add_learnings_to_context: bool | None = meta_field(
        "memory", "Add learnings to the context", widget="switch", default=True, order=6
    )

    # ---------------------------------------------------------------- history & summaries
    add_history_to_context: bool | None = meta_field(
        "context", "Add history to the context", widget="switch", default=False, order=1
    )
    num_history_runs: int | None = meta_field("context", "Runs of history", widget="number", order=2)
    num_history_messages: int | None = meta_field("context", "Messages of history", widget="number", order=3)
    max_tool_calls_from_history: int | None = meta_field(
        "context", "Tool calls kept from history", widget="number", order=4
    )
    enable_session_summaries: bool | None = meta_field(
        "context", "Session summaries", widget="switch", default=False, order=5
    )
    add_session_summary_to_context: bool | None = meta_field(
        "context", "Add the summary to the context", widget="switch", order=6
    )
    search_past_sessions: bool | None = meta_field(
        "context", "Search past sessions", widget="switch", default=False, order=7
    )
    num_past_sessions_to_search: int | None = meta_field("context", "Past sessions to search", widget="number", order=8)
    read_chat_history: bool | None = meta_field(
        "context", "Tool to read the chat history", widget="switch", default=False, order=9
    )

    # ---------------------------------------------------------------- output
    input_schema: str | dict[str, Any] | None = meta_field("output", "Input schema", widget="schema", order=2)
    output_schema: str | dict[str, Any] | None = meta_field(
        "output",
        "Output schema",
        help="A schema registered on the instance, or an inline JSON Schema.",
        widget="schema",
        order=1,
    )
    use_json_mode: bool | None = meta_field("output", "JSON mode", widget="switch", default=False, order=3)
    parse_response: bool | None = meta_field("output", "Parse the response", widget="switch", default=True, order=4)

    # ---------------------------------------------------------------- session state
    session_state: dict[str, Any] | None = meta_field("session_state", "Initial session state", widget="json", order=1)
    add_session_state_to_context: bool | None = meta_field(
        "session_state", "Add the state to the context", widget="switch", default=False, order=2
    )
    enable_agentic_state: bool | None = meta_field(
        "session_state", "Let the model update the state", widget="switch", default=False, order=3
    )

    # ---------------------------------------------------------------- advanced
    dependencies: dict[str, Any] | None = meta_field("advanced", "Dependencies", widget="json", order=30)
    add_dependencies_to_context: bool | None = meta_field(
        "advanced", "Add dependencies to the context", widget="switch", default=False, order=31
    )
    store_media: bool | None = meta_field("advanced", "Store media", widget="switch", default=True, order=40)
    store_tool_messages: bool | None = meta_field(
        "advanced", "Store tool messages", widget="switch", default=True, order=41
    )
    store_history_messages: bool | None = meta_field(
        "advanced", "Store history messages", widget="switch", default=False, order=42
    )
    send_media_to_model: bool | None = meta_field(
        "advanced", "Send media to the model", widget="switch", default=True, order=43
    )
    resolve_in_context: bool | None = meta_field(
        "advanced", "Resolve placeholders in the context", widget="switch", default=True, order=44
    )
    compress_tool_results: bool | None = meta_field(
        "advanced", "Compress tool results", widget="switch", default=False, order=45
    )
    system_message_role: str | None = meta_field("advanced", "System message role", default="system", order=46)
