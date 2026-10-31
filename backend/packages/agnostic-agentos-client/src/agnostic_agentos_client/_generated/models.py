# Generated from openapi/agentos-3.1.12.json by datamodel-code-generator. Do not edit; run `just agentos-client-gen`.

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class AgentSessionDetailSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_data: Annotated[
        dict[str, Any] | None,
        Field(description='Agent-specific data', title='Agent Data'),
    ] = None
    agent_id: Annotated[
        str | None, Field(description='Agent ID used in this session', title='Agent Id')
    ] = None
    agent_session_id: Annotated[
        str,
        Field(description='Unique agent session identifier', title='Agent Session Id'),
    ]
    chat_history: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Complete chat history', title='Chat History'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Session creation timestamp', title='Created At'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None, Field(description='Session metrics', title='Metrics')
    ] = None
    session_id: Annotated[
        str, Field(description='Session identifier', title='Session Id')
    ]
    session_name: Annotated[
        str, Field(description='Human-readable session name', title='Session Name')
    ]
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Current state of the session', title='Session State'),
    ] = None
    session_summary: Annotated[
        dict[str, Any] | None,
        Field(description='Summary of session interactions', title='Session Summary'),
    ] = None
    total_tokens: Annotated[
        int | None,
        Field(description='Total tokens used in this session', title='Total Tokens'),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(description='Last update timestamp', title='Updated At'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None


class ApprovalCountResponse(BaseModel):
    """
    Response model for pending approval count.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    count: Annotated[int, Field(title='Count')]


class ResolvedBy(RootModel[str]):
    root: Annotated[str, Field(max_length=255, title='Resolved By')]


class ApprovalResolve(BaseModel):
    """
    Request body for resolving (approve/reject) an approval.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    resolution_data: Annotated[
        dict[str, Any] | None, Field(title='Resolution Data')
    ] = None
    resolved_by: Annotated[ResolvedBy | None, Field(title='Resolved By')] = None
    status: Annotated[str, Field(pattern='^(approved|rejected)$', title='Status')]


class ApprovalStatusResponse(BaseModel):
    """
    Lightweight response model for polling approval status.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    approval_id: Annotated[str, Field(title='Approval Id')]
    resolved_at: Annotated[int | None, Field(title='Resolved At')] = None
    resolved_by: Annotated[str | None, Field(title='Resolved By')] = None
    run_id: Annotated[str, Field(title='Run Id')]
    status: Annotated[str, Field(title='Status')]


class BadRequestResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[
        str, Field(description='Human-readable error message', title='Detail')
    ]
    error_id: Annotated[
        str | None,
        Field(
            description='Stable identifier for the specific error, present only when the error carries one',
            title='Error Id',
        ),
    ] = None
    error_type: Annotated[
        str | None,
        Field(
            description='Category of the error, present only when the error carries one',
            title='Error Type',
        ),
    ] = None


class BodyContinueAgentRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    additional_instructions: Annotated[
        str | None,
        Field(
            description='Only valid with ``regenerate=true``: extra guidance appended as a user message before re-generation. Friendly alias for ``input``.',
            title='Additional Instructions',
        ),
    ] = None
    background: Annotated[
        bool | None,
        Field(
            description='Run continue in background (survives client disconnect). Requires database. Use /resume to reconnect.',
            title='Background',
        ),
    ] = False
    continue_from: Annotated[
        str | None,
        Field(
            description="Continuation boundary. Use 'end', 'last_user', or a numeric message index.",
            title='Continue From',
        ),
    ] = 'end'
    fork: Annotated[
        bool | None,
        Field(
            description='When true, clone the run with a new ``run_id`` before resuming. The original is untouched; the clone becomes a sibling within the same session, with ``forked_from_run_id`` set.',
            title='Fork',
        ),
    ] = False
    input: Annotated[
        str | None,
        Field(
            description='Optional new user-message text to append to the run before resuming. Use for continuing a COMPLETED run with a follow-up, or adding context to a RUNNING/ERROR resume.',
            title='Input',
        ),
    ] = None
    regenerate: Annotated[
        bool | None,
        Field(
            description="Sugar: regenerate the last response of this run. Auto-computes ``continue_from='last_user'`` to land just after the last user message. Pair with ``additional_instructions`` to steer the new output. By default the original response is hidden from history (replaced); pass ``replace_original=false`` to keep both the original and the regenerated response visible side by side.",
            title='Regenerate',
        ),
    ] = False
    replace_original: Annotated[
        bool | None,
        Field(
            description='Only valid with ``regenerate=true``. Controls history visibility of the original response; the original run is always retained in storage. Defaults to true: the original is marked REGENERATED and hidden from history so the new response replaces it. Pass false to keep both the original and regenerated responses visible.',
            title='Replace Original',
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description='Session ID for the paused run', title='Session Id'),
    ] = None
    stream: Annotated[
        bool | None,
        Field(
            description='Enable streaming responses via Server-Sent Events (SSE)',
            title='Stream',
        ),
    ] = True
    tools: Annotated[
        str | None,
        Field(
            description='JSON string of tool call results to continue the paused run',
            title='Tools',
        ),
    ] = ''
    user_id: Annotated[
        str | None,
        Field(
            description='User identifier for tracking and personalization',
            title='User Id',
        ),
    ] = None


class BodyContinueTeamRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    additional_instructions: Annotated[
        str | None, Field(title='Additional Instructions')
    ] = None
    background: Annotated[bool | None, Field(title='Background')] = False
    continue_from: Annotated[
        str | None,
        Field(
            description="Continuation boundary. Use 'end', 'last_user', or a numeric message index.",
            title='Continue From',
        ),
    ] = 'end'
    fork: Annotated[bool | None, Field(title='Fork')] = False
    input: Annotated[str | None, Field(title='Input')] = None
    regenerate: Annotated[bool | None, Field(title='Regenerate')] = False
    replace_original: Annotated[bool | None, Field(title='Replace Original')] = None
    requirements: Annotated[str | None, Field(title='Requirements')] = ''
    session_id: Annotated[str | None, Field(title='Session Id')] = None
    stream: Annotated[bool | None, Field(title='Stream')] = True
    user_id: Annotated[str | None, Field(title='User Id')] = None


class BodyContinueWorkflowRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    background: Annotated[
        bool | None,
        Field(
            description='Continue in background (survives client disconnect). Requires database. Use /resume to reconnect.',
            title='Background',
        ),
    ] = False
    factory_input: Annotated[
        str | None,
        Field(
            description='JSON object with factory-specific parameters for dynamic workflow reconstruction',
            title='Factory Input',
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description='Session ID for the paused run', title='Session Id'),
    ] = None
    step_requirements: Annotated[
        str | None,
        Field(
            description='JSON string of step requirement objects with resolution status',
            title='Step Requirements',
        ),
    ] = ''
    stream: Annotated[
        bool | None,
        Field(
            description='Enable streaming responses via Server-Sent Events (SSE)',
            title='Stream',
        ),
    ] = True
    user_id: Annotated[
        str | None,
        Field(
            description='User identifier for tracking and personalization',
            title='User Id',
        ),
    ] = None


class BodyCreateAgentRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    background: Annotated[
        bool | None,
        Field(
            description='Run in background and return immediately with run metadata (requires database)',
            title='Background',
        ),
    ] = False
    factory_input: Annotated[
        str | None,
        Field(
            description='JSON object with factory-specific parameters for dynamic agent construction',
            title='Factory Input',
        ),
    ] = None
    files: Annotated[
        list[str] | None,
        Field(
            description='Files to upload (images, audio, video, or documents)',
            title='Files',
        ),
    ] = None
    files_metadata: Annotated[
        str | None,
        Field(
            description='JSON array of per-file metadata objects, matched to files[] by position',
            title='Files Metadata',
        ),
    ] = None
    message: Annotated[
        str,
        Field(
            description='The input message or prompt to send to the agent',
            title='Message',
        ),
    ]
    session_id: Annotated[
        str | None,
        Field(
            description='Session ID for conversation continuity. If not provided, a new session is created',
            title='Session Id',
        ),
    ] = None
    stream: Annotated[
        bool | None,
        Field(
            description='Enable streaming responses via Server-Sent Events (SSE)',
            title='Stream',
        ),
    ] = True
    user_id: Annotated[
        str | None,
        Field(
            description='User identifier for tracking and personalization',
            title='User Id',
        ),
    ] = None
    version: Annotated[
        int | None,
        Field(description='Agent version to use for this run', title='Version'),
    ] = None


class BodyCreateTeamRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    background: Annotated[
        bool | None,
        Field(
            description='Run in background and return immediately with run metadata (requires database)',
            title='Background',
        ),
    ] = False
    factory_input: Annotated[
        str | None,
        Field(
            description='JSON object with factory-specific parameters for dynamic team construction',
            title='Factory Input',
        ),
    ] = None
    files: Annotated[
        list[str] | None,
        Field(
            description='Files to upload (images, audio, video, or documents)',
            title='Files',
        ),
    ] = None
    files_metadata: Annotated[
        str | None,
        Field(
            description='JSON array of per-file metadata objects, matched to files[] by position',
            title='Files Metadata',
        ),
    ] = None
    message: Annotated[
        str,
        Field(
            description='The input message or prompt to send to the team',
            title='Message',
        ),
    ]
    monitor: Annotated[
        bool | None,
        Field(
            description='Enable monitoring and logging for this run', title='Monitor'
        ),
    ] = True
    session_id: Annotated[
        str | None,
        Field(
            description='Session ID for conversation continuity. If not provided, a new session is created',
            title='Session Id',
        ),
    ] = None
    stream: Annotated[
        bool | None,
        Field(
            description='Enable streaming responses via Server-Sent Events (SSE)',
            title='Stream',
        ),
    ] = True
    user_id: Annotated[
        str | None,
        Field(
            description='User identifier for tracking and personalization',
            title='User Id',
        ),
    ] = None
    version: Annotated[
        int | None,
        Field(description='Team version to use for this run', title='Version'),
    ] = None


class BodyCreateWorkflowRun(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    background: Annotated[
        bool | None,
        Field(
            description='Run workflow in background (survives client disconnect). Requires database. Use /resume to reconnect.',
            title='Background',
        ),
    ] = False
    factory_input: Annotated[
        str | None,
        Field(
            description='JSON object with factory-specific parameters for dynamic workflow construction',
            title='Factory Input',
        ),
    ] = None
    message: Annotated[
        str,
        Field(
            description='The input message or prompt to send to the workflow',
            title='Message',
        ),
    ]
    session_id: Annotated[
        str | None,
        Field(
            description='Session ID for conversation continuity. If not provided, a new session is created',
            title='Session Id',
        ),
    ] = None
    stream: Annotated[
        bool | None,
        Field(
            description='Enable streaming responses via Server-Sent Events (SSE)',
            title='Stream',
        ),
    ] = True
    user_id: Annotated[
        str | None,
        Field(
            description='User identifier for tracking and personalization',
            title='User Id',
        ),
    ] = None
    version: Annotated[
        int | None,
        Field(description='Workflow version to use for this run', title='Version'),
    ] = None


class BodyRenameSession(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    session_name: Annotated[
        str, Field(description='New name for the session', title='Session Name')
    ]


class BodyResumeAgentRunStream(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    last_event_index: Annotated[
        int | None,
        Field(
            description='Index of last event received by client (0-based)',
            title='Last Event Index',
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description='Session ID for database fallback', title='Session Id'),
    ] = None


class BodyResumeTeamRunStream(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    last_event_index: Annotated[
        int | None,
        Field(
            description='Index of last event received by client (0-based)',
            title='Last Event Index',
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description='Session ID for database fallback', title='Session Id'),
    ] = None


class BodyResumeWorkflowRunStream(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    last_event_index: Annotated[
        int | None,
        Field(
            description='Index of last event received by client (0-based)',
            title='Last Event Index',
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(description='Session ID for database fallback', title='Session Id'),
    ] = None


class BodyUpdateContent(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[
        str | None, Field(description='Content description', title='Description')
    ] = None
    metadata: Annotated[
        str | None,
        Field(description='Content metadata as JSON string', title='Metadata'),
    ] = None
    name: Annotated[str | None, Field(description='Content name', title='Name')] = None
    reader_id: Annotated[
        str | None,
        Field(description='ID of the reader to use for processing', title='Reader Id'),
    ] = None


class BodyUploadContent(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    chunk_overlap: Annotated[
        int | None,
        Field(description='Chunk overlap to use for processing', title='Chunk Overlap'),
    ] = None
    chunk_size: Annotated[
        int | None,
        Field(description='Chunk size to use for processing', title='Chunk Size'),
    ] = None
    chunker: Annotated[
        str | None,
        Field(
            description='Chunking strategy to apply during processing', title='Chunker'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(description='Content description for context', title='Description'),
    ] = None
    file: Annotated[
        str | None, Field(description='File to upload for processing', title='File')
    ] = None
    metadata: Annotated[
        str | None,
        Field(
            description='JSON metadata object for additional content properties',
            title='Metadata',
        ),
    ] = None
    name: Annotated[
        str | None,
        Field(
            description='Content name (auto-generated from file/URL if not provided)',
            title='Name',
        ),
    ] = None
    reader_id: Annotated[
        str | None,
        Field(
            description='ID of the reader to use for content processing',
            title='Reader Id',
        ),
    ] = None
    text_content: Annotated[
        str | None,
        Field(description='Raw text content to process', title='Text Content'),
    ] = None
    url: Annotated[
        str | None,
        Field(
            description='Single URL string, optionally JSON encoded. Submit multiple URLs in separate requests.',
            title='Url',
        ),
    ] = None


class BodyUploadRemoteContent(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    chunk_overlap: Annotated[
        int | None,
        Field(description='Chunk overlap for processing', title='Chunk Overlap'),
    ] = None
    chunk_size: Annotated[
        int | None, Field(description='Chunk size for processing', title='Chunk Size')
    ] = None
    chunker: Annotated[
        str | None, Field(description='Chunking strategy to apply', title='Chunker')
    ] = None
    config_id: Annotated[
        str,
        Field(
            description='ID of the configured remote content source (from /knowledge/config)',
            title='Config Id',
        ),
    ]
    description: Annotated[
        str | None, Field(description='Content description', title='Description')
    ] = None
    metadata: Annotated[
        str | None, Field(description='JSON metadata object', title='Metadata')
    ] = None
    name: Annotated[
        str | None,
        Field(
            description='Content name (auto-generated if not provided)', title='Name'
        ),
    ] = None
    path: Annotated[
        str,
        Field(description='Path to file or folder in the remote source', title='Path'),
    ]
    reader_id: Annotated[
        str | None,
        Field(description='ID of the reader to use for processing', title='Reader Id'),
    ] = None
    source_params: Annotated[
        str | None,
        Field(
            description="JSON object of per-request parameters forwarded to the source's factory. Used for provider-specific routing that shouldn't be baked into the config. Currently supported keys: GitHub accepts 'repo' ('owner/repo'), letting one configured GitHub source serve multiple repositories the credentials can access.",
            title='Source Params',
        ),
    ] = None


class ChatConfig(BaseModel):
    """
    Configuration for the Chat page of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    quick_prompts: Annotated[dict[str, list[str]], Field(title='Quick Prompts')]


class ChunkerSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[str | None, Field(title='Description')] = None
    key: Annotated[str, Field(title='Key')]
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    name: Annotated[str | None, Field(title='Name')] = None


class CompanyDomainConfig(BaseModel):
    """
    Display configuration for the Company domain.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class ComponentConfigResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    component_id: Annotated[str, Field(title='Component Id')]
    config: Annotated[dict[str, Any], Field(title='Config')]
    created_at: Annotated[int, Field(title='Created At')]
    label: Annotated[str | None, Field(title='Label')] = None
    notes: Annotated[str | None, Field(title='Notes')] = None
    stage: Annotated[str, Field(title='Stage')]
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    version: Annotated[int, Field(title='Version')]


class ComponentGuard(BaseModel):
    """
    Optional compare-and-set guard for component writes.

    When present, each non-None field is checked against the stored state and
    the write is rejected with 409 on mismatch. None fields skip that half of
    the check; omitting the guard keeps the write last-writer-wins.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    current_version: Annotated[
        int | None,
        Field(
            description='Expected current (published) version; 0 expects the component to have none yet',
            title='Current Version',
        ),
    ] = None
    latest_version: Annotated[
        int | None,
        Field(description='Expected latest config version', title='Latest Version'),
    ] = None


class ComponentType(StrEnum):
    agent = 'agent'
    team = 'team'
    workflow = 'workflow'


class ComponentUpdate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    component_type: Annotated[str | None, Field(title='Component Type')] = None
    current_version: Annotated[int | None, Field(title='Current Version')] = None
    description: Annotated[str | None, Field(title='Description')] = None
    guard: ComponentGuard | None = None
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    name: Annotated[str | None, Field(title='Name')] = None


class ConfigCreate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    config: Annotated[
        dict[str, Any], Field(description='The configuration data', title='Config')
    ]
    guard: Annotated[
        ComponentGuard | None, Field(description='Optional compare-and-set guard')
    ] = None
    label: Annotated[
        str | None, Field(description="Optional label (e.g., 'stable')", title='Label')
    ] = None
    links: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Optional links to child components', title='Links'),
    ] = None
    notes: Annotated[str | None, Field(description='Optional notes', title='Notes')] = (
        None
    )
    set_current: Annotated[
        bool | None, Field(description='Set as current version', title='Set Current')
    ] = True
    stage: Annotated[
        str | None, Field(description="Stage: 'draft' or 'published'", title='Stage')
    ] = 'draft'
    version: Annotated[
        int | None, Field(description='Optional version number', title='Version')
    ] = None


class ConfigResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    config: Annotated[dict[str, Any] | None, Field(title='Config')] = None
    guard: ComponentGuard | None = None
    label: Annotated[str | None, Field(title='Label')] = None
    links: Annotated[list[dict[str, Any]] | None, Field(title='Links')] = None
    notes: Annotated[str | None, Field(title='Notes')] = None
    stage: Annotated[str | None, Field(title='Stage')] = None


class AccessCount(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description='Number of times content has been accessed',
            ge=0,
            title='Access Count',
        ),
    ]


class ContentStatus(StrEnum):
    """
    Enumeration of possible content processing statuses.
    """

    processing = 'processing'
    completed = 'completed'
    partial = 'partial'
    failed = 'failed'


class ContentStatusResponse(BaseModel):
    """
    Response model for content status endpoint.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    id: Annotated[str | None, Field(description='Content ID', title='Id')] = None
    status: Annotated[
        ContentStatus, Field(description='Current processing status of the content')
    ]
    status_message: Annotated[
        str | None,
        Field(description='Status message or error details', title='Status Message'),
    ] = ''


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID if this is an agent session', title='Agent Id'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    session_id: Annotated[
        str | None,
        Field(
            description='Optional session ID (generated if not provided)',
            title='Session Id',
        ),
    ] = None
    session_name: Annotated[
        str | None, Field(description='Name for the session', title='Session Name')
    ] = None
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Initial session state', title='Session State'),
    ] = None
    team_id: Annotated[
        str | None,
        Field(description='Team ID if this is a team session', title='Team Id'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(
            description='Workflow ID if this is a workflow session', title='Workflow Id'
        ),
    ] = None


class DatabaseConfigCompanyDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: CompanyDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DayAggregatedMetrics(BaseModel):
    """
    Aggregated metrics for a given day
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_runs_count: Annotated[
        int,
        Field(description='Total number of agent runs', ge=0, title='Agent Runs Count'),
    ]
    agent_sessions_count: Annotated[
        int,
        Field(
            description='Total number of agent sessions',
            ge=0,
            title='Agent Sessions Count',
        ),
    ]
    created_at: Annotated[
        AwareDatetime,
        Field(description='Timestamp when metrics were created', title='Created At'),
    ]
    date: Annotated[
        AwareDatetime,
        Field(description='Date for which these metrics are aggregated', title='Date'),
    ]
    id: Annotated[
        str, Field(description='Unique identifier for the metrics record', title='Id')
    ]
    model_metrics: Annotated[
        list[dict[str, Any]],
        Field(
            description='Metrics grouped by model (model_id, provider, count)',
            title='Model Metrics',
        ),
    ]
    team_runs_count: Annotated[
        int,
        Field(description='Total number of team runs', ge=0, title='Team Runs Count'),
    ]
    team_sessions_count: Annotated[
        int,
        Field(
            description='Total number of team sessions',
            ge=0,
            title='Team Sessions Count',
        ),
    ]
    token_metrics: Annotated[
        dict[str, Any],
        Field(
            description='Token usage metrics (input, output, cached, etc.)',
            title='Token Metrics',
        ),
    ]
    updated_at: Annotated[
        AwareDatetime,
        Field(
            description='Timestamp when metrics were last updated', title='Updated At'
        ),
    ]
    users_count: Annotated[
        int,
        Field(description='Total number of unique users', ge=0, title='Users Count'),
    ]
    workflow_runs_count: Annotated[
        int,
        Field(
            description='Total number of workflow runs',
            ge=0,
            title='Workflow Runs Count',
        ),
    ]
    workflow_sessions_count: Annotated[
        int,
        Field(
            description='Total number of workflow sessions',
            ge=0,
            title='Workflow Sessions Count',
        ),
    ]


class DeleteEvalRunsRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    eval_run_ids: Annotated[
        list[str],
        Field(
            description='List of evaluation run IDs to delete',
            min_length=1,
            title='Eval Run Ids',
        ),
    ]


class DeleteMemoriesRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    memory_ids: Annotated[
        list[str],
        Field(
            description='List of memory IDs to delete', min_length=1, title='Memory Ids'
        ),
    ]
    user_id: Annotated[
        str | None,
        Field(description='User ID to filter memories for deletion', title='User Id'),
    ] = None


class EvalFilterType(StrEnum):
    agent = 'agent'
    team = 'team'
    workflow = 'workflow'


class ScoringStrategy(StrEnum):
    """
    Scoring strategy: 'numeric' (1-10 with threshold) or 'binary' (PASS/FAIL)
    """

    numeric = 'numeric'
    binary = 'binary'


class Threshold(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description='Score threshold for pass/fail (1-10), only used with numeric scoring',
            ge=1,
            le=10,
            title='Threshold',
        ),
    ] = 7


class EvalType(StrEnum):
    accuracy = 'accuracy'
    agent_as_judge = 'agent_as_judge'
    performance = 'performance'
    reliability = 'reliability'


class EvalsDomainConfig(BaseModel):
    """
    Configuration for the Evals domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class Access(StrEnum):
    """
    Agent access to this namespace. Omitted for full access; tool-specific restrictions still apply.
    """

    full = 'full'
    read_only = 'read_only'


class FileSystemAgent(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    access: Annotated[
        Access | None,
        Field(
            description='Agent access to this namespace. Omitted for full access; tool-specific restrictions still apply.',
            title='Access',
        ),
    ] = 'full'
    id: Annotated[
        str,
        Field(description='ID of an agent using this filesystem namespace', title='Id'),
    ]


class FileSystemContentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_ids: Annotated[list[str], Field(title='Agent Ids')]
    content: Annotated[str, Field(title='Content')]
    limit: Annotated[int, Field(title='Limit')]
    line_count: Annotated[int, Field(title='Line Count')]
    namespace: Annotated[str, Field(title='Namespace')]
    next_offset: Annotated[int | None, Field(title='Next Offset')] = None
    offset: Annotated[int, Field(title='Offset')]
    path: Annotated[str, Field(title='Path')]
    size_bytes: Annotated[int, Field(title='Size Bytes')]
    truncated: Annotated[bool, Field(title='Truncated')]
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None
    version: Annotated[int | None, Field(title='Version')] = None


class Type(StrEnum):
    file = 'file'
    directory = 'directory'


class FileSystemEntry(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    path: Annotated[str, Field(title='Path')]
    size_bytes: Annotated[int | None, Field(title='Size Bytes')] = None
    type: Annotated[Type, Field(title='Type')]
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None
    version: Annotated[int | None, Field(title='Version')] = None


class FileSystemNamespace(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agents: Annotated[
        list[FileSystemAgent],
        Field(
            description='Agents using this filesystem namespace and their access',
            title='Agents',
        ),
    ]
    backend_type: Annotated[
        str, Field(description='Filesystem backend type', title='Backend Type')
    ]
    db_id: Annotated[
        str | None,
        Field(
            description='Database identifier for a database-backed filesystem',
            title='Db Id',
        ),
    ] = None
    db_schema: Annotated[
        str | None,
        Field(
            description='Database schema containing filesystem rows', title='Db Schema'
        ),
    ] = None
    max_file_bytes: Annotated[
        int, Field(description='Maximum UTF-8 bytes per file', title='Max File Bytes')
    ]
    max_namespace_bytes: Annotated[
        int,
        Field(
            description='Maximum bytes across the namespace',
            title='Max Namespace Bytes',
        ),
    ]
    namespace: Annotated[
        str,
        Field(
            description='Canonical namespace resolved for the caller; placeholders remain when identity is unavailable',
            title='Namespace',
        ),
    ]
    table_name: Annotated[
        str | None,
        Field(
            description='Database table containing filesystem rows', title='Table Name'
        ),
    ] = None
    user_isolation: Annotated[
        bool,
        Field(
            description='Whether the namespace is partitioned by user identity',
            title='User Isolation',
        ),
    ]


class FileSystemSearchEntry(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    line: Annotated[int | None, Field(title='Line')] = None
    match_count: Annotated[int, Field(title='Match Count')]
    path: Annotated[str, Field(title='Path')]
    size_bytes: Annotated[int, Field(title='Size Bytes')]
    snippet: Annotated[str, Field(title='Snippet')]
    user_id: Annotated[str | None, Field(title='User Id')] = None


class FileSystemTableEntry(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_ids: Annotated[list[str], Field(title='Agent Ids')]
    line: Annotated[int | None, Field(title='Line')] = None
    match_count: Annotated[int | None, Field(title='Match Count')] = None
    namespace: Annotated[str, Field(title='Namespace')]
    path: Annotated[str, Field(title='Path')]
    size_bytes: Annotated[int, Field(title='Size Bytes')]
    snippet: Annotated[str | None, Field(title='Snippet')] = None
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None
    version: Annotated[int | None, Field(title='Version')] = None


class FileSystemUsage(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    bytes_limit: Annotated[int, Field(title='Bytes Limit')]
    file_count: Annotated[int, Field(title='File Count')]
    total_bytes: Annotated[int, Field(title='Total Bytes')]


class FilterFieldSchema(BaseModel):
    """
    Schema describing a single filterable field for the frontend filter bar.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    key: Annotated[
        str,
        Field(description='Column/field name used in filter expressions', title='Key'),
    ]
    label: Annotated[
        str, Field(description='Human-readable display label for the UI', title='Label')
    ]
    operators: Annotated[
        list[str],
        Field(
            description='List of valid filter operators for this field',
            title='Operators',
        ),
    ]
    type: Annotated[
        str,
        Field(
            description='Field data type: string, number, datetime, enum', title='Type'
        ),
    ]
    values: Annotated[
        list[str] | None,
        Field(
            description='Allowed enum values (for autocomplete/dropdown)',
            title='Values',
        ),
    ] = None


class FilterSchemaResponse(BaseModel):
    """
    Response for the filter schema endpoint. Tells the FE what fields, operators, and values are available.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    fields: Annotated[
        list[FilterFieldSchema],
        Field(description='Available filterable fields', title='Fields'),
    ]
    logical_operators: Annotated[
        list[str] | None,
        Field(
            description='Logical operators for combining filter clauses',
            title='Logical Operators',
        ),
    ] = ['AND', 'OR']


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    instantiated_at: Annotated[
        AwareDatetime,
        Field(
            description='Timestamp when service was instantiated',
            title='Instantiated At',
        ),
    ]
    status: Annotated[
        str, Field(description='Health status of the service', title='Status')
    ]


class AuthMode(StrEnum):
    """
    Authentication mode enforced on the REST/WS plane of this OS instance. MCP OAuth, when enabled, is described separately under `mcp.oauth`.
    """

    none = 'none'
    security_key = 'security_key'
    jwt = 'jwt'


class InterfaceResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    route: Annotated[str, Field(description='API route path', title='Route')]
    type: Annotated[str, Field(description='Type of the interface', title='Type')]
    version: Annotated[
        str, Field(description='Version of the interface', title='Version')
    ]


class InternalServerErrorResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[
        str, Field(description='Human-readable error message', title='Detail')
    ]
    error_id: Annotated[
        str | None,
        Field(
            description='Stable identifier for the specific error, present only when the error carries one',
            title='Error Id',
        ),
    ] = None
    error_type: Annotated[
        str | None,
        Field(
            description='Category of the error, present only when the error carries one',
            title='Error Type',
        ),
    ] = None


class KnowledgeDomainConfig(BaseModel):
    """
    Configuration for the Knowledge domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class KnowledgeInstanceConfig(BaseModel):
    """
    Configuration for a single knowledge instance
    """

    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    description: Annotated[str | None, Field(title='Description')] = None
    id: Annotated[str, Field(title='Id')]
    name: Annotated[str, Field(title='Name')]
    table: Annotated[str, Field(title='Table')]


class LearningCreate(BaseModel):
    """
    Request body for creating a learning record.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None, Field(description='Associated agent ID', title='Agent Id')
    ] = None
    content: Annotated[
        dict[str, Any],
        Field(description='The learning content payload', title='Content'),
    ]
    entity_id: Annotated[
        str | None, Field(description='Associated entity ID', title='Entity Id')
    ] = None
    entity_type: Annotated[
        str | None, Field(description='Entity type', title='Entity Type')
    ] = None
    learning_type: Annotated[
        str,
        Field(
            description="Type of learning (e.g. 'user_profile', 'entity_memory')",
            title='Learning Type',
        ),
    ]
    metadata: Annotated[
        dict[str, Any] | None, Field(description='Optional metadata', title='Metadata')
    ] = None
    namespace: Annotated[
        str | None,
        Field(
            description="Namespace for scoping ('user', 'global', or custom)",
            title='Namespace',
        ),
    ] = None
    session_id: Annotated[
        str | None, Field(description='Associated session ID', title='Session Id')
    ] = None
    team_id: Annotated[
        str | None, Field(description='Associated team ID', title='Team Id')
    ] = None
    user_id: Annotated[
        str | None,
        Field(
            description='Associated user ID. When the request is authenticated, must match the JWT subject or be omitted/null (which creates a global / non-user-scoped record).',
            title='User Id',
        ),
    ] = None


class LearningDomainConfig(BaseModel):
    """
    Configuration for the Learning domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class LearningResponse(BaseModel):
    """
    A single learning record as returned by the API.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None, Field(description='Associated agent ID', title='Agent Id')
    ] = None
    content: Annotated[
        dict[str, Any] | None,
        Field(description='The learning content payload', title='Content'),
    ] = None
    created_at: Annotated[
        int | None,
        Field(
            description='Creation timestamp (Unix epoch seconds)', title='Created At'
        ),
    ] = None
    entity_id: Annotated[
        str | None,
        Field(
            description='Associated entity ID (for entity-specific learnings)',
            title='Entity Id',
        ),
    ] = None
    entity_type: Annotated[
        str | None,
        Field(
            description="Entity type (e.g. 'person', 'company')", title='Entity Type'
        ),
    ] = None
    learning_id: Annotated[
        str,
        Field(
            description='Unique identifier for the learning record', title='Learning Id'
        ),
    ]
    learning_type: Annotated[
        str,
        Field(
            description="Type of learning (e.g. 'user_profile', 'entity_memory')",
            title='Learning Type',
        ),
    ]
    metadata: Annotated[
        dict[str, Any] | None, Field(description='Optional metadata', title='Metadata')
    ] = None
    namespace: Annotated[
        str | None,
        Field(
            description="Namespace for scoping ('user', 'global', or custom)",
            title='Namespace',
        ),
    ] = None
    session_id: Annotated[
        str | None, Field(description='Associated session ID', title='Session Id')
    ] = None
    team_id: Annotated[
        str | None, Field(description='Associated team ID', title='Team Id')
    ] = None
    updated_at: Annotated[
        int | None,
        Field(
            description='Last update timestamp (Unix epoch seconds)', title='Updated At'
        ),
    ] = None
    user_id: Annotated[
        str | None, Field(description='Associated user ID', title='User Id')
    ] = None


class LearningUpdate(BaseModel):
    """
    Request body for updating a learning record. Identity fields are immutable.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    content: Annotated[
        dict[str, Any] | None,
        Field(description='Replacement content payload', title='Content'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Replacement metadata', title='Metadata'),
    ] = None


class LearningUserStats(BaseModel):
    """
    A user that owns learning records, with their most recent activity.

    Used as a lightweight index for the per-user view: list users here, then drill into a
    single user's records via ``GET /learnings?user_id=...``. No per-user count is returned
    -- the user-scoped stores (``user_profile``, ``user_memory``) keep a single record per
    user, so a record count would always be 1; the actual memory count lives in that
    record's ``content``.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    last_learning_updated_at: Annotated[
        int | None,
        Field(
            description='Most recent learning update for this user (Unix epoch seconds)',
            title='Last Learning Updated At',
        ),
    ] = None
    user_id: Annotated[str, Field(description='The user ID', title='User Id')]


class Manifest(BaseModel):
    """
    OS-level UI metadata for an agent/team/workflow.

    Fields here are AgentOS UI metadata only. ``description`` is unrelated to
    ``Agent.description`` / ``Team.description`` / ``Workflow.description``,
    which are sent to the model.

    Rendering surfaces:
    - ``description``, ``labels``: home/landing card
    - ``quick_prompts``: chat page
    """

    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[str | None, Field(title='Description')] = None
    labels: Annotated[list[str] | None, Field(title='Labels')] = None
    quick_prompts: Annotated[list[str] | None, Field(title='Quick Prompts')] = None


class McpOAuthInfo(BaseModel):
    """
    OAuth discovery details for an MCP endpoint protected by ``AgentOS(mcp_auth=...)``.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    authorization_servers: Annotated[
        list[str] | None,
        Field(
            description='Issuer URL(s) of the authorization server(s) protecting the MCP endpoint',
            title='Authorization Servers',
        ),
    ] = None
    resource: Annotated[
        str | None,
        Field(
            description='RFC 9728 resource URL advertised for the MCP endpoint',
            title='Resource',
        ),
    ] = None


class MemoryDomainConfig(BaseModel):
    """
    Configuration for the Memory domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class Meta(BaseModel):
    """
    Inline metadata schema for pagination.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    limit: Annotated[
        int | None, Field(description='Number of results per page', ge=1, title='Limit')
    ] = 20
    page: Annotated[
        int | None, Field(description='Page number', ge=1, title='Page')
    ] = 1


class MetricsDomainConfig(BaseModel):
    """
    Configuration for the Metrics domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class MetricsRefreshResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    message: Annotated[
        str | None, Field(description='Additional details', title='Message')
    ] = None
    status: Annotated[
        str, Field(description='Status of the refresh request', title='Status')
    ]


class MetricsRefreshStatusResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    error: Annotated[
        str | None,
        Field(
            description='Error message if the most recent refresh failed', title='Error'
        ),
    ] = None
    finished_at: Annotated[
        AwareDatetime | None,
        Field(description='When the most recent refresh finished', title='Finished At'),
    ] = None
    started_at: Annotated[
        AwareDatetime | None,
        Field(description='When the most recent refresh started', title='Started At'),
    ] = None
    status: Annotated[
        str,
        Field(
            description="Refresh status: 'idle', 'running', 'completed' or 'failed'",
            title='Status',
        ),
    ]


class MetricsResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    metrics: Annotated[
        list[DayAggregatedMetrics],
        Field(description='List of daily aggregated metrics', title='Metrics'),
    ]
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Timestamp of the most recent metrics update',
            title='Updated At',
        ),
    ] = None


class Model(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    id: Annotated[str | None, Field(description='Model identifier', title='Id')] = None
    provider: Annotated[
        str | None, Field(description='Model provider name', title='Provider')
    ] = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    model: Annotated[
        str | None, Field(description='Model identifier', title='Model')
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the model', title='Name')
    ] = None
    provider: Annotated[
        str | None, Field(description='Model provider name', title='Provider')
    ] = None


class NotFoundResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[
        str, Field(description='Human-readable error message', title='Detail')
    ]
    error_id: Annotated[
        str | None,
        Field(
            description='Stable identifier for the specific error, present only when the error carries one',
            title='Error Id',
        ),
    ] = None
    error_type: Annotated[
        str | None,
        Field(
            description='Category of the error, present only when the error carries one',
            title='Error Type',
        ),
    ] = None


class OptimizeMemoriesRequest(BaseModel):
    """
    Schema for memory optimization request
    """

    model_config = ConfigDict(
        extra='allow',
    )
    apply: Annotated[
        bool | None,
        Field(
            description='If True, apply optimization changes to database. If False, return preview only without saving.',
            title='Apply',
        ),
    ] = True
    model: Annotated[
        str | None,
        Field(
            description="Model to use for optimization in format 'provider:model_id' (e.g., 'openai:gpt-4o-mini', 'anthropic:claude-3-5-sonnet-20241022', 'google:gemini-2.0-flash-exp'). If not specified, uses MemoryManager's default model (gpt-4o).",
            title='Model',
        ),
    ] = None
    user_id: Annotated[
        str, Field(description='User ID to optimize memories for', title='User Id')
    ]


class PaginationInfo(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    limit: Annotated[
        int | None, Field(description='Number of items per page', ge=1, title='Limit')
    ] = 20
    page: Annotated[
        int | None,
        Field(description='Current page number (1-indexed)', ge=0, title='Page'),
    ] = 0
    search_time_ms: Annotated[
        float | None,
        Field(
            description='Search execution time in milliseconds',
            ge=0.0,
            title='Search Time Ms',
        ),
    ] = 0
    total_count: Annotated[
        int | None, Field(description='Total count of items', ge=0, title='Total Count')
    ] = 0
    total_pages: Annotated[
        int | None,
        Field(description='Total number of pages', ge=0, title='Total Pages'),
    ] = 0


class QueueCapabilities(BaseModel):
    """
    Deployment-level background-run capabilities: what a client may rely on
    when deciding whether to render queue-aware UI (e.g. a chat tray).

    Reported as EFFECTIVE behavior, not raw settings: queue_per_session is
    true only when a durable queue actually enforces the per-session gate -
    a queue_per_session flag without durable=True, or with a custom store
    that does not serialize sessions, gates nothing and is reported false. Readable by any authenticated caller (deployment
    capability, not operator data - the admin-scoped /queue surface stays
    the only view of actual jobs).

    Both fields describe submissions the durable queue can carry. A
    background submission the queue cannot carry (media uploads, payloads
    plain JSON cannot store, factory-backed or off-registry components)
    executes in-process on the accepting replica, outside the gate and
    without durability, and the server logs each such bypass; the client
    still receives 202 PENDING. A caller that sends those knows it is
    sending them; the capability does not change per submission.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    durable: Annotated[
        bool,
        Field(
            description='Accepted background runs survive crashes and deploys (ticketed queue with a worker)',
            title='Durable',
        ),
    ]
    queue_per_session: Annotated[
        bool,
        Field(
            description='Same-session background submissions execute at most one at a time, FIFO by submission; false when no durable queue enforces the gate',
            title='Queue Per Session',
        ),
    ]


class QueueJobSchema(BaseModel):
    """
    One durable queue job (a background run's queue ticket).
    """

    model_config = ConfigDict(
        extra='allow',
    )
    attempt: Annotated[
        int | None, Field(description='Executions started so far', title='Attempt')
    ] = 0
    available_at: Annotated[
        int | None,
        Field(
            description='Epoch seconds the job becomes claimable', title='Available At'
        ),
    ] = None
    completed_at: Annotated[
        int | None,
        Field(
            description='Epoch seconds the job reached a terminal state',
            title='Completed At',
        ),
    ] = None
    component_id: Annotated[
        str,
        Field(
            description='ID of the agent/team/workflow the run executes on',
            title='Component Id',
        ),
    ]
    component_type: Annotated[
        str,
        Field(
            description='Component kind: agent, team or workflow',
            title='Component Type',
        ),
    ]
    created_at: Annotated[
        int | None,
        Field(description='Epoch seconds the job was accepted', title='Created At'),
    ] = None
    error: Annotated[
        str | None,
        Field(description='Terminal error of the last attempt, if any', title='Error'),
    ] = None
    id: Annotated[
        str, Field(description="Job ID (identical to the run's run_id)", title='Id')
    ]
    idempotency_key: Annotated[
        str | None,
        Field(
            description='Client-provided dedupe key, if any', title='Idempotency Key'
        ),
    ] = None
    job_type: Annotated[
        str | None,
        Field(
            description='Kind of work the ticket carries (runs only today)',
            title='Job Type',
        ),
    ] = 'run'
    locked_at: Annotated[
        int | None,
        Field(
            description='Epoch seconds the current lock was taken', title='Locked At'
        ),
    ] = None
    locked_by: Annotated[
        str | None,
        Field(description="Worker currently holding the job's lock", title='Locked By'),
    ] = None
    max_attempts: Annotated[
        int | None,
        Field(
            description='Execution budget under any failure mode', title='Max Attempts'
        ),
    ] = 1
    payload: Annotated[
        dict[str, Any] | None,
        Field(description='Serialized run parameters', title='Payload'),
    ] = None
    session_id: Annotated[
        str, Field(description='Session the run belongs to', title='Session Id')
    ]
    status: Annotated[
        str,
        Field(
            description='queued | running | completed | failed | cancelled | paused',
            title='Status',
        ),
    ]
    updated_at: Annotated[
        int | None,
        Field(description='Epoch seconds of the last state change', title='Updated At'),
    ] = None
    user_id: Annotated[
        str | None, Field(description='User the run was submitted for', title='User Id')
    ] = None


class ReaderSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    chunkers: Annotated[
        list[str] | None,
        Field(description='List of supported chunking strategies', title='Chunkers'),
    ] = None
    content_types: Annotated[
        list[str] | None,
        Field(
            description='Content types this reader can read in this install',
            title='Content Types',
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description="Description of the reader's capabilities", title='Description'
        ),
    ] = None
    id: Annotated[
        str, Field(description='Unique identifier for the reader', title='Id')
    ]
    name: Annotated[
        str | None, Field(description='Name of the reader', title='Name')
    ] = None
    unavailable_content_types: Annotated[
        dict[str, list[str]] | None,
        Field(
            description='Content types this reader supports but cannot read here, and the packages each needs',
            title='Unavailable Content Types',
        ),
    ] = None


class RegistryResourceType(StrEnum):
    """
    Types of resources that can be stored in a registry.
    """

    tool = 'tool'
    model = 'model'
    db = 'db'
    vector_db = 'vector_db'
    schema = 'schema'
    function = 'function'
    agent = 'agent'
    team = 'team'
    workflow = 'workflow'
    knowledge = 'knowledge'
    memory_manager = 'memory_manager'
    session_summary_manager = 'session_summary_manager'
    learning = 'learning'


class RemoteContentSourceSchema(BaseModel):
    """
    Schema for remote content source configuration.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    id: Annotated[
        str, Field(description='Unique identifier for the content source', title='Id')
    ]
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Custom metadata for the content source', title='Metadata'),
    ] = None
    name: Annotated[
        str, Field(description='Display name for the content source', title='Name')
    ]
    prefix: Annotated[
        str | None,
        Field(description='Default path prefix for this source', title='Prefix'),
    ] = None
    type: Annotated[
        str,
        Field(
            description='Type of content source (s3, gcs, sharepoint, github, azureblob)',
            title='Type',
        ),
    ]


class RunSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID that executed this run', title='Agent Id'),
    ] = None
    audio: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Audio files included in the run', title='Audio'),
    ] = None
    cancellation_stage: Annotated[
        str | None,
        Field(
            description='For CANCELLED runs, where the run was when it was cancelled: PENDING, EXECUTING, PAUSED. Absent means unknown.',
            title='Cancellation Stage',
        ),
    ] = None
    citations: Annotated[
        dict[str, Any] | None,
        Field(
            description='Citations from the model (e.g., from Gemini grounding/search)',
            title='Citations',
        ),
    ] = None
    content: Annotated[
        str | dict[str, Any] | None,
        Field(description='Output content from the run', title='Content'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Run creation timestamp', title='Created At'),
    ] = None
    events: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Events generated during the run', title='Events'),
    ] = None
    files: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Files included in the run', title='Files'),
    ] = None
    followups: Annotated[
        list[str] | None,
        Field(
            description='Followup suggestions generated after the run',
            title='Followups',
        ),
    ] = None
    forked_from_message_index: Annotated[
        int | None,
        Field(
            description='If this run was forked, the message index at which the source was truncated',
            title='Forked From Message Index',
        ),
    ] = None
    forked_from_run_id: Annotated[
        str | None,
        Field(
            description="If this run was forked from another run, the source run's ID",
            title='Forked From Run Id',
        ),
    ] = None
    forked_from_session_id: Annotated[
        str | None,
        Field(
            description="If this run was created via session branch, the source session's ID",
            title='Forked From Session Id',
        ),
    ] = None
    images: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Images included in the run', title='Images'),
    ] = None
    input_media: Annotated[
        dict[str, Any] | None,
        Field(description='Input media attachments', title='Input Media'),
    ] = None
    last_checkpoint_at_message_index: Annotated[
        int | None,
        Field(
            description="Message index of the most recent mid-run checkpoint (checkpoint='tool-batch' runs)",
            title='Last Checkpoint At Message Index',
        ),
    ] = None
    messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Message history for the run', title='Messages'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            description='Run metadata, including sdk for external agent sessions',
            title='Metadata',
        ),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None,
        Field(description='Performance and usage metrics', title='Metrics'),
    ] = None
    parent_run_id: Annotated[
        str | None,
        Field(
            description='Parent run ID if this is a nested run', title='Parent Run Id'
        ),
    ] = None
    reasoning_content: Annotated[
        str | None,
        Field(
            description='Reasoning content if reasoning was enabled',
            title='Reasoning Content',
        ),
    ] = None
    reasoning_messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Reasoning process messages', title='Reasoning Messages'),
    ] = None
    reasoning_steps: Annotated[
        list[dict[str, Any]] | None,
        Field(description='List of reasoning steps', title='Reasoning Steps'),
    ] = None
    references: Annotated[
        list[dict[str, Any]] | None,
        Field(description='References cited in the run', title='References'),
    ] = None
    regenerated_from: Annotated[
        str | None,
        Field(
            description="If this run was produced via regenerate=true, the source run's ID",
            title='Regenerated From',
        ),
    ] = None
    response_audio: Annotated[
        dict[str, Any] | None,
        Field(description='Audio response if generated', title='Response Audio'),
    ] = None
    run_id: Annotated[
        str, Field(description='Unique identifier for the run', title='Run Id')
    ]
    run_input: Annotated[
        str | None, Field(description='Input provided to the run', title='Run Input')
    ] = None
    run_response_format: Annotated[
        str | None,
        Field(
            description='Format of the response (text/json)',
            title='Run Response Format',
        ),
    ] = None
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Session state at the end of the run', title='Session State'),
    ] = None
    status: Annotated[
        str | None,
        Field(
            description='Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)',
            title='Status',
        ),
    ] = None
    tools: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Tools used in the run', title='Tools'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the run', title='User Id'),
    ] = None
    videos: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Videos included in the run', title='Videos'),
    ] = None


class RunStatus(StrEnum):
    """
    State of the main run response
    """

    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    PAUSED = 'PAUSED'
    CANCELLED = 'CANCELLED'
    ERROR = 'ERROR'
    REGENERATED = 'REGENERATED'


class Description(RootModel[str]):
    root: Annotated[str, Field(max_length=1024, title='Description')]


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    cron_expr: Annotated[
        str | None,
        Field(
            description='An empty or omitted cron makes the schedule on demand; it runs only through trigger.',
            max_length=128,
            title='Cron Expr',
        ),
    ] = ''
    description: Annotated[Description | None, Field(title='Description')] = None
    endpoint: Annotated[str, Field(max_length=512, title='Endpoint')]
    max_retries: Annotated[int | None, Field(ge=0, le=10, title='Max Retries')] = 0
    method: Annotated[str | None, Field(max_length=10, title='Method')] = 'POST'
    name: Annotated[str, Field(max_length=255, title='Name')]
    payload: Annotated[dict[str, Any] | None, Field(title='Payload')] = None
    retry_delay_seconds: Annotated[
        int | None, Field(ge=1, le=3600, title='Retry Delay Seconds')
    ] = 60
    timeout_seconds: Annotated[
        int | None, Field(ge=1, le=86400, title='Timeout Seconds')
    ] = 3600
    timezone: Annotated[str | None, Field(max_length=64, title='Timezone')] = 'UTC'


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    created_at: Annotated[int | None, Field(title='Created At')] = None
    cron_expr: Annotated[str | None, Field(title='Cron Expr')] = None
    description: Annotated[str | None, Field(title='Description')] = None
    disabled_reason: Annotated[str | None, Field(title='Disabled Reason')] = None
    enabled: Annotated[bool, Field(title='Enabled')]
    endpoint: Annotated[str, Field(title='Endpoint')]
    id: Annotated[str, Field(title='Id')]
    managed_by: Annotated[str | None, Field(title='Managed By')] = None
    max_retries: Annotated[int, Field(title='Max Retries')]
    method: Annotated[str, Field(title='Method')]
    name: Annotated[str, Field(title='Name')]
    next_run_at: Annotated[int | None, Field(title='Next Run At')] = None
    payload: Annotated[dict[str, Any] | None, Field(title='Payload')] = None
    retry_delay_seconds: Annotated[int, Field(title='Retry Delay Seconds')]
    target_id: Annotated[str | None, Field(title='Target Id')] = None
    target_type: Annotated[str | None, Field(title='Target Type')] = None
    timeout_seconds: Annotated[int, Field(title='Timeout Seconds')]
    timezone: Annotated[str, Field(title='Timezone')]
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None


class ScheduleRunResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    attempt: Annotated[int, Field(title='Attempt')]
    completed_at: Annotated[int | None, Field(title='Completed At')] = None
    created_at: Annotated[int | None, Field(title='Created At')] = None
    error: Annotated[str | None, Field(title='Error')] = None
    id: Annotated[str, Field(title='Id')]
    input: Annotated[dict[str, Any] | None, Field(title='Input')] = None
    output: Annotated[dict[str, Any] | None, Field(title='Output')] = None
    requirements: Annotated[
        list[dict[str, Any]] | None, Field(title='Requirements')
    ] = None
    run_id: Annotated[str | None, Field(title='Run Id')] = None
    schedule_id: Annotated[str, Field(title='Schedule Id')]
    session_id: Annotated[str | None, Field(title='Session Id')] = None
    status: Annotated[str, Field(title='Status')]
    status_code: Annotated[int | None, Field(title='Status Code')] = None
    triggered_at: Annotated[int | None, Field(title='Triggered At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None


class ScheduleStateResponse(BaseModel):
    """
    Trimmed response for state-changing operations (enable/disable).
    """

    model_config = ConfigDict(
        extra='allow',
    )
    enabled: Annotated[bool, Field(title='Enabled')]
    id: Annotated[str, Field(title='Id')]
    name: Annotated[str, Field(title='Name')]
    next_run_at: Annotated[int | None, Field(title='Next Run At')] = None
    updated_at: Annotated[int | None, Field(title='Updated At')] = None


class CronExpr(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='An empty cron makes the schedule on demand; it runs only through trigger. Omit to keep the current cron.',
            max_length=128,
            title='Cron Expr',
        ),
    ]


class Endpoint(RootModel[str]):
    root: Annotated[str, Field(max_length=512, title='Endpoint')]


class MaxRetries(RootModel[int]):
    root: Annotated[int, Field(ge=0, le=10, title='Max Retries')]


class Method(RootModel[str]):
    root: Annotated[str, Field(max_length=10, title='Method')]


class Name(RootModel[str]):
    root: Annotated[str, Field(max_length=255, title='Name')]


class RetryDelaySeconds(RootModel[int]):
    root: Annotated[int, Field(ge=1, le=3600, title='Retry Delay Seconds')]


class TimeoutSeconds(RootModel[int]):
    root: Annotated[int, Field(ge=1, le=86400, title='Timeout Seconds')]


class Timezone(RootModel[str]):
    root: Annotated[str, Field(max_length=64, title='Timezone')]


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    cron_expr: Annotated[
        CronExpr | None,
        Field(
            description='An empty cron makes the schedule on demand; it runs only through trigger. Omit to keep the current cron.',
            title='Cron Expr',
        ),
    ] = None
    description: Annotated[Description | None, Field(title='Description')] = None
    endpoint: Annotated[Endpoint | None, Field(title='Endpoint')] = None
    max_retries: Annotated[MaxRetries | None, Field(title='Max Retries')] = None
    method: Annotated[Method | None, Field(title='Method')] = None
    name: Annotated[Name | None, Field(title='Name')] = None
    payload: Annotated[dict[str, Any] | None, Field(title='Payload')] = None
    retry_delay_seconds: Annotated[
        RetryDelaySeconds | None, Field(title='Retry Delay Seconds')
    ] = None
    timeout_seconds: Annotated[
        TimeoutSeconds | None, Field(title='Timeout Seconds')
    ] = None
    timezone: Annotated[Timezone | None, Field(title='Timezone')] = None


class Effect(StrEnum):
    """
    'allow' or 'deny'
    """

    allow = 'allow'
    deny = 'deny'


class ScopeItem(BaseModel):
    """
    Write shape for one scope grant — the canonical RBAC payload for every scope-bearing API.

    Endpoints that take scopes accept these objects only (a bare string is a validation
    error). ``effect`` is constrained here so every consumer rejects typos at the model
    layer; whether ``deny`` is *semantically* legal stays per-endpoint (roles support
    deny rules, service-account tokens are pure grants and reject it).
    """

    model_config = ConfigDict(
        extra='allow',
    )
    effect: Annotated[
        Effect | None, Field(description="'allow' or 'deny'", title='Effect')
    ] = 'allow'
    scope: Annotated[
        str, Field(description="Scope string, e.g. 'agents:*:run'", title='Scope')
    ]


class ScopeSchema(BaseModel):
    """
    Read shape for one scope — the parsed RBAC payload shared by every scope-bearing API.

    Mirrors the cloud RBAC scope shape ({raw, namespace, sub_namespace, permission, value})
    so a frontend renders scopes from any AgentOS API with one integration.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    id: Annotated[
        str | None,
        Field(
            description='Scope id (always null here; kept for shape parity with the cloud RBAC API, which addresses scopes individually)',
            title='Id',
        ),
    ] = None
    namespace: Annotated[
        str, Field(description="Resource namespace, e.g. 'agents'", title='Namespace')
    ]
    permission: Annotated[
        str,
        Field(description="Action, e.g. 'read' / 'run' / 'write'", title='Permission'),
    ]
    raw: Annotated[
        str,
        Field(description="Original scope string, e.g. 'agents:*:run'", title='Raw'),
    ]
    sub_namespace: Annotated[
        str | None,
        Field(
            description="Specific resource id or wildcard '*'", title='Sub Namespace'
        ),
    ] = None
    value: Annotated[
        str | None, Field(description="'allow' or 'deny'", title='Value')
    ] = 'allow'


class ExpiresInDays(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description='Days until the token expires (default: 90)',
            ge=1,
            le=3650,
            title='Expires In Days',
        ),
    ] = 90


class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    allow_privileged_scopes: Annotated[
        bool | None,
        Field(
            description='Required to grant privileged scopes: any write or delete action, the admin scope, or any service_accounts scope. Privileged tokens must be deliberate, never accidental.',
            title='Allow Privileged Scopes',
        ),
    ] = False
    expires_in_days: Annotated[
        ExpiresInDays | None,
        Field(
            description='Days until the token expires (default: 90)',
            title='Expires In Days',
            validate_default=True,
        ),
    ] = 90
    name: Annotated[
        str,
        Field(
            description="Machine identity name (lowercase slug), e.g. 'claude-code' or 'github-actions'",
            max_length=63,
            title='Name',
        ),
    ]
    never_expires: Annotated[
        bool | None,
        Field(
            description='Mint a non-expiring token. Must be set explicitly; overrides expires_in_days.',
            title='Never Expires',
        ),
    ] = False
    scopes: Annotated[
        list[ScopeItem] | None,
        Field(
            description="Scopes granted to the token, as {scope, effect} objects (the shared RBAC write shape; token scopes are grants, so only effect='allow' is accepted). Defaults to run and read scopes: agents:run, teams:run, workflows:run, sessions:read",
            title='Scopes',
        ),
    ] = None


class ServiceAccountCreateResponse(BaseModel):
    """
    Returned once, at creation. The token is never retrievable again.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    created_at: Annotated[int, Field(title='Created At')]
    created_by: Annotated[str | None, Field(title='Created By')] = None
    expires_at: Annotated[int | None, Field(title='Expires At')] = None
    id: Annotated[str, Field(title='Id')]
    last_used_at: Annotated[int | None, Field(title='Last Used At')] = None
    name: Annotated[str, Field(title='Name')]
    principal: Annotated[
        str,
        Field(
            description="The user_id attached to runs made with this token, e.g. 'sa:claude-code'",
            title='Principal',
        ),
    ]
    revoked_at: Annotated[int | None, Field(title='Revoked At')] = None
    scopes: Annotated[
        list[ScopeSchema] | None,
        Field(
            description='Scopes granted to the token, in the shared RBAC read shape',
            title='Scopes',
        ),
    ] = None
    token: Annotated[
        str,
        Field(
            description='The plaintext token. Shown exactly once - store it securely now.',
            title='Token',
        ),
    ]
    token_prefix: Annotated[
        str,
        Field(
            description='First characters of the token, for display only',
            title='Token Prefix',
        ),
    ]
    user_id: Annotated[
        str | None,
        Field(
            description='The user this account belongs to; None for workspace-level accounts. Distinct from created_by, which records who minted the token.',
            title='User Id',
        ),
    ] = None


class ServiceAccountResponse(BaseModel):
    """
    Service account metadata. Never includes the token hash or plaintext.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    created_at: Annotated[int, Field(title='Created At')]
    created_by: Annotated[str | None, Field(title='Created By')] = None
    expires_at: Annotated[int | None, Field(title='Expires At')] = None
    id: Annotated[str, Field(title='Id')]
    last_used_at: Annotated[int | None, Field(title='Last Used At')] = None
    name: Annotated[str, Field(title='Name')]
    principal: Annotated[
        str,
        Field(
            description="The user_id attached to runs made with this token, e.g. 'sa:claude-code'",
            title='Principal',
        ),
    ]
    revoked_at: Annotated[int | None, Field(title='Revoked At')] = None
    scopes: Annotated[
        list[ScopeSchema] | None,
        Field(
            description='Scopes granted to the token, in the shared RBAC read shape',
            title='Scopes',
        ),
    ] = None
    token_prefix: Annotated[
        str,
        Field(
            description='First characters of the token, for display only',
            title='Token Prefix',
        ),
    ]
    user_id: Annotated[
        str | None,
        Field(
            description='The user this account belongs to; None for workspace-level accounts. Distinct from created_by, which records who minted the token.',
            title='User Id',
        ),
    ] = None


class SessionDomainConfig(BaseModel):
    """
    Configuration for the Session domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class SessionRunPreviewSchema(BaseModel):
    """
    Lightweight session-run listing entry: the shape a queue tray or
    session sidebar polls for. Deliberately excludes messages, events, media,
    metrics and step results - the full shapes stay on the default listing
    and the single-run endpoint. Previews are truncated to 280 characters.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID, when this is an agent run', title='Agent Id'),
    ] = None
    content_preview: Annotated[
        str | None,
        Field(description='Output content preview, truncated', title='Content Preview'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Run creation timestamp', title='Created At'),
    ] = None
    parent_run_id: Annotated[
        str | None,
        Field(
            description='Parent run ID if this is a nested run', title='Parent Run Id'
        ),
    ] = None
    run_id: Annotated[
        str, Field(description='Unique identifier for the run', title='Run Id')
    ]
    run_input: Annotated[
        str | None, Field(description='Input preview, truncated', title='Run Input')
    ] = None
    status: Annotated[
        str | None,
        Field(
            description='Run status (PENDING, RUNNING, PAUSED, COMPLETED, CANCELLED, ERROR, REGENERATED)',
            title='Status',
        ),
    ] = None
    team_id: Annotated[
        str | None,
        Field(description='Team ID, when this is a team run', title='Team Id'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the run', title='User Id'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(
            description='Workflow ID, when this is a workflow run', title='Workflow Id'
        ),
    ] = None


class SessionSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID if this is an agent session', title='Agent Id'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Timestamp when session was created', title='Created At'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None, Field(description='Session metrics', title='Metrics')
    ] = None
    session_id: Annotated[
        str, Field(description='Unique identifier for the session', title='Session Id')
    ]
    session_name: Annotated[
        str,
        Field(description='Human-readable name for the session', title='Session Name'),
    ]
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Current state data of the session', title='Session State'),
    ] = None
    session_summary: Annotated[
        dict[str, Any] | None,
        Field(description='Summary of session interactions', title='Session Summary'),
    ] = None
    session_type: Annotated[
        str | None,
        Field(
            description='Type of session: agent, team, or workflow',
            title='Session Type',
        ),
    ] = None
    team_id: Annotated[
        str | None,
        Field(description='Team ID if this is a team session', title='Team Id'),
    ] = None
    total_tokens: Annotated[
        int | None,
        Field(description='Total tokens used in this session', title='Total Tokens'),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Timestamp when session was last updated', title='Updated At'
        ),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(
            description='Workflow ID if this is a workflow session', title='Workflow Id'
        ),
    ] = None


class SortBy(StrEnum):
    created_at = 'created_at'
    updated_at = 'updated_at'


class SortOrder(StrEnum):
    asc = 'asc'
    desc = 'desc'


class SessionType(StrEnum):
    agent = 'agent'
    team = 'team'
    workflow = 'workflow'


class SetCurrentRequest(BaseModel):
    """
    Body for set-current. Optional: an empty POST keeps working.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    guard: Annotated[
        ComponentGuard | None, Field(description='Optional compare-and-set guard')
    ] = None


class SourceFileSchema(BaseModel):
    """
    Schema for a file in a content source.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    content_type: Annotated[
        str | None, Field(description='MIME type of the file', title='Content Type')
    ] = None
    key: Annotated[str, Field(description='Full path/key of the file', title='Key')]
    last_modified: Annotated[
        AwareDatetime | None,
        Field(
            description='ISO 8601 timestamp of last modification', title='Last Modified'
        ),
    ] = None
    name: Annotated[str, Field(description='Display name (filename)', title='Name')]
    size: Annotated[
        int | None, Field(description='File size in bytes', title='Size')
    ] = None


class SourceFolderSchema(BaseModel):
    """
    Schema for a folder in a content source.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    is_empty: Annotated[
        bool | None,
        Field(description='Whether the folder contains any files', title='Is Empty'),
    ] = False
    name: Annotated[str, Field(description='Display name of the folder', title='Name')]
    prefix: Annotated[
        str,
        Field(
            description='Full prefix to use for navigating into this folder',
            title='Prefix',
        ),
    ]


class TeamRunSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    audio: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Audio files included in the run', title='Audio'),
    ] = None
    cancellation_stage: Annotated[
        str | None,
        Field(
            description='For CANCELLED runs, where the run was when it was cancelled: PENDING, EXECUTING, PAUSED. Absent means unknown.',
            title='Cancellation Stage',
        ),
    ] = None
    citations: Annotated[
        dict[str, Any] | None,
        Field(
            description='Citations from the model (e.g., from Gemini grounding/search)',
            title='Citations',
        ),
    ] = None
    content: Annotated[
        str | dict[str, Any] | None,
        Field(description='Output content from the team run', title='Content'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Run creation timestamp', title='Created At'),
    ] = None
    events: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Events generated during the run', title='Events'),
    ] = None
    files: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Files included in the run', title='Files'),
    ] = None
    followups: Annotated[
        list[str] | None,
        Field(
            description='Followup suggestions generated after the run',
            title='Followups',
        ),
    ] = None
    forked_from_message_index: Annotated[
        int | None,
        Field(
            description='If this team run was forked, the message index at which the source was truncated',
            title='Forked From Message Index',
        ),
    ] = None
    forked_from_run_id: Annotated[
        str | None,
        Field(
            description="If this team run was forked from another run, the source run's ID",
            title='Forked From Run Id',
        ),
    ] = None
    forked_from_session_id: Annotated[
        str | None,
        Field(
            description="If this team run was created via session branch, the source session's ID",
            title='Forked From Session Id',
        ),
    ] = None
    images: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Images included in the run', title='Images'),
    ] = None
    input_media: Annotated[
        dict[str, Any] | None,
        Field(description='Input media attachments', title='Input Media'),
    ] = None
    last_checkpoint_at_message_index: Annotated[
        int | None,
        Field(
            description="Message index of the most recent mid-run checkpoint (checkpoint='tool-batch' runs)",
            title='Last Checkpoint At Message Index',
        ),
    ] = None
    messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Message history for the run', title='Messages'),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None,
        Field(description='Performance and usage metrics', title='Metrics'),
    ] = None
    parent_run_id: Annotated[
        str | None,
        Field(
            description='Parent run ID if this is a nested run', title='Parent Run Id'
        ),
    ] = None
    reasoning_content: Annotated[
        str | None,
        Field(
            description='Reasoning content if reasoning was enabled',
            title='Reasoning Content',
        ),
    ] = None
    reasoning_messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Reasoning process messages', title='Reasoning Messages'),
    ] = None
    reasoning_steps: Annotated[
        list[dict[str, Any]] | None,
        Field(description='List of reasoning steps', title='Reasoning Steps'),
    ] = None
    references: Annotated[
        list[dict[str, Any]] | None,
        Field(description='References cited in the run', title='References'),
    ] = None
    regenerated_from: Annotated[
        str | None,
        Field(
            description="If this team run was produced via regenerate=true, the source run's ID",
            title='Regenerated From',
        ),
    ] = None
    response_audio: Annotated[
        dict[str, Any] | None,
        Field(description='Audio response if generated', title='Response Audio'),
    ] = None
    run_id: Annotated[
        str, Field(description='Unique identifier for the team run', title='Run Id')
    ]
    run_input: Annotated[
        str | None, Field(description='Input provided to the run', title='Run Input')
    ] = None
    run_response_format: Annotated[
        str | None,
        Field(
            description='Format of the response (text/json)',
            title='Run Response Format',
        ),
    ] = None
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Session state at the end of the run', title='Session State'),
    ] = None
    status: Annotated[
        str | None,
        Field(
            description='Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)',
            title='Status',
        ),
    ] = None
    team_id: Annotated[
        str | None, Field(description='Team ID that executed this run', title='Team Id')
    ] = None
    tools: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Tools used in the run', title='Tools'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the run', title='User Id'),
    ] = None
    videos: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Videos included in the run', title='Videos'),
    ] = None


class TeamSessionDetailSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    chat_history: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Complete chat history', title='Chat History'),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Session creation timestamp', title='Created At'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None, Field(description='Session metrics', title='Metrics')
    ] = None
    session_id: Annotated[
        str, Field(description='Unique session identifier', title='Session Id')
    ]
    session_name: Annotated[
        str, Field(description='Human-readable session name', title='Session Name')
    ]
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Current state of the session', title='Session State'),
    ] = None
    session_summary: Annotated[
        dict[str, Any] | None,
        Field(description='Summary of team interactions', title='Session Summary'),
    ] = None
    team_data: Annotated[
        dict[str, Any] | None,
        Field(description='Team-specific data', title='Team Data'),
    ] = None
    team_id: Annotated[
        str | None, Field(description='Team ID used in this session', title='Team Id')
    ] = None
    total_tokens: Annotated[
        int | None,
        Field(description='Total tokens used in this session', title='Total Tokens'),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(description='Last update timestamp', title='Updated At'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None


class TeamSummaryResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[
        str | None, Field(description='Database identifier', title='Db Id')
    ] = None
    description: Annotated[
        str | None, Field(description='Description of the team', title='Description')
    ] = None
    id: Annotated[
        str | None, Field(description='Unique identifier for the team', title='Id')
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Framework component metadata', title='Metadata'),
    ] = None
    mode: Annotated[
        str | None,
        Field(
            description='Team execution mode (coordinate, route, broadcast, tasks)',
            title='Mode',
        ),
    ] = None
    model: Annotated[
        Model | None, Field(description='Model used by the team leader')
    ] = None
    name: Annotated[str | None, Field(description='Name of the team', title='Name')] = (
        None
    )
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False


class TraceNode(BaseModel):
    """
    Recursive node structure for rendering trace hierarchy in the frontend
    """

    model_config = ConfigDict(
        extra='allow',
    )
    duration: Annotated[
        str,
        Field(
            description="Human-readable duration (e.g., '123ms', '1.5s')",
            title='Duration',
        ),
    ]
    end_time: Annotated[
        AwareDatetime,
        Field(
            description='End time (Pydantic auto-serializes to ISO 8601)',
            title='End Time',
        ),
    ]
    error: Annotated[
        str | None, Field(description='Error message if status is ERROR', title='Error')
    ] = None
    extra_data: Annotated[
        dict[str, Any] | None,
        Field(
            description='Flexible field for custom attributes and additional data',
            title='Extra Data',
        ),
    ] = None
    id: Annotated[str, Field(description='Span ID', title='Id')]
    input: Annotated[
        str | None, Field(description='Input to the span', title='Input')
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional span attributes and data', title='Metadata'),
    ] = None
    name: Annotated[
        str,
        Field(description="Span name (e.g., 'agent.run', 'llm.invoke')", title='Name'),
    ]
    output: Annotated[
        str | None, Field(description='Output from the span', title='Output')
    ] = None
    spans: Annotated[
        list[TraceNode] | None,
        Field(description='Child spans in the trace hierarchy', title='Spans'),
    ] = None
    start_time: Annotated[
        AwareDatetime,
        Field(
            description='Start time (Pydantic auto-serializes to ISO 8601)',
            title='Start Time',
        ),
    ]
    status: Annotated[str, Field(description='Status code (OK, ERROR)', title='Status')]
    step_type: Annotated[
        str | None,
        Field(
            description='Workflow step type (Step, Condition, function, Agent, Team)',
            title='Step Type',
        ),
    ] = None
    type: Annotated[
        str,
        Field(description='Span kind (AGENT, TEAM, WORKFLOW, LLM, TOOL)', title='Type'),
    ]


class TraceSearchGroupBy(StrEnum):
    """
    Grouping options for trace search results.
    """

    run = 'run'
    session = 'session'


class TraceSearchRequest(BaseModel):
    """
    Request body for POST /traces/search with advanced filtering.

    The filter field accepts a FilterExpr DSL dict supporting composable queries
    with AND/OR/NOT logic and operators like EQ, NEQ, GT, GTE, LT, LTE, IN, CONTAINS, STARTSWITH.

    Example for run grouping (default):
        {
            "filter": {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "CONTAINS", "key": "user_id", "value": "admin"}
                ]
            },
            "group_by": "run",
            "page": 1,
            "limit": 20
        }

    Example for session grouping:
        {
            "filter": {"op": "EQ", "key": "agent_id", "value": "my-agent"},
            "group_by": "session",
            "page": 1,
            "limit": 20
        }
    """

    model_config = ConfigDict(
        extra='allow',
    )
    filter: Annotated[
        dict[str, Any] | None,
        Field(
            description='FilterExpr DSL as JSON dict. Supports operators: EQ, NEQ, GT, GTE, LT, LTE, IN, CONTAINS, STARTSWITH, AND, OR, NOT.',
            title='Filter',
        ),
    ] = None
    group_by: Annotated[
        TraceSearchGroupBy | None,
        Field(
            description="Grouping mode: 'run' returns individual TraceDetail, 'session' returns aggregated TraceSessionStats."
        ),
    ] = 'run'
    limit: Annotated[
        int | None,
        Field(
            description='Number of traces per page (max 100)',
            ge=1,
            le=100,
            title='Limit',
        ),
    ] = 20
    page: Annotated[
        int | None, Field(description='Page number (1-indexed)', ge=1, title='Page')
    ] = 1


class TraceSessionStats(BaseModel):
    """
    Aggregated trace statistics grouped by session
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID(s) used in the session', title='Agent Id'),
    ] = None
    first_trace_at: Annotated[
        AwareDatetime,
        Field(
            description='Time of first trace (Pydantic auto-serializes to ISO 8601)',
            title='First Trace At',
        ),
    ]
    last_trace_at: Annotated[
        AwareDatetime,
        Field(
            description='Time of last trace (Pydantic auto-serializes to ISO 8601)',
            title='Last Trace At',
        ),
    ]
    session_id: Annotated[
        str, Field(description='Session identifier', title='Session Id')
    ]
    team_id: Annotated[
        str | None,
        Field(description='Team ID associated with the session', title='Team Id'),
    ] = None
    total_traces: Annotated[
        int,
        Field(
            description='Total number of traces in this session', title='Total Traces'
        ),
    ]
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(
            description='Workflow ID associated with the session', title='Workflow Id'
        ),
    ] = None


class TraceSummary(BaseModel):
    """
    Summary information for trace list view
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None, Field(description='Associated agent ID', title='Agent Id')
    ] = None
    created_at: Annotated[
        AwareDatetime,
        Field(
            description='Time when trace was created (Pydantic auto-serializes to ISO 8601)',
            title='Created At',
        ),
    ]
    duration: Annotated[
        str, Field(description='Human-readable total duration', title='Duration')
    ]
    end_time: Annotated[
        AwareDatetime,
        Field(
            description='Trace end time (Pydantic auto-serializes to ISO 8601)',
            title='End Time',
        ),
    ]
    error_count: Annotated[
        int, Field(description='Number of spans with errors', title='Error Count')
    ]
    input: Annotated[
        str | None, Field(description='Input to the agent', title='Input')
    ] = None
    name: Annotated[
        str, Field(description='Trace name (usually root span name)', title='Name')
    ]
    run_id: Annotated[
        str | None, Field(description='Associated run ID', title='Run Id')
    ] = None
    session_id: Annotated[
        str | None, Field(description='Associated session ID', title='Session Id')
    ] = None
    start_time: Annotated[
        AwareDatetime,
        Field(
            description='Trace start time (Pydantic auto-serializes to ISO 8601)',
            title='Start Time',
        ),
    ]
    status: Annotated[
        str, Field(description='Overall status (OK, ERROR, UNSET)', title='Status')
    ]
    team_id: Annotated[
        str | None, Field(description='Associated team ID', title='Team Id')
    ] = None
    total_spans: Annotated[
        int,
        Field(description='Total number of spans in this trace', title='Total Spans'),
    ]
    trace_id: Annotated[
        str, Field(description='Unique trace identifier', title='Trace Id')
    ]
    user_id: Annotated[
        str | None, Field(description='Associated user ID', title='User Id')
    ] = None
    workflow_id: Annotated[
        str | None, Field(description='Associated workflow ID', title='Workflow Id')
    ] = None


class TracesDomainConfig(BaseModel):
    """
    Configuration for the Traces domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[
        str, Field(description='Human-readable error message', title='Detail')
    ]
    error_id: Annotated[
        str | None,
        Field(
            description='Stable identifier for the specific error, present only when the error carries one',
            title='Error Id',
        ),
    ] = None
    error_type: Annotated[
        str | None,
        Field(
            description='Category of the error, present only when the error carries one',
            title='Error Type',
        ),
    ] = None


class UnavailableChunkerSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[
        str | None,
        Field(description='Description of the chunking strategy', title='Description'),
    ] = None
    id: Annotated[
        str, Field(description='Chunker key that could not be loaded', title='Id')
    ]
    missing_packages: Annotated[
        list[str] | None,
        Field(description='Packages that are not importable', title='Missing Packages'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the chunker', title='Name')
    ] = None
    reason: Annotated[
        str,
        Field(
            description='Verbatim import failure, including its install instruction',
            title='Reason',
        ),
    ]


class UnavailableReaderSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[
        str | None,
        Field(
            description="Description of the reader's capabilities", title='Description'
        ),
    ] = None
    id: Annotated[
        str, Field(description='Reader key that could not be loaded', title='Id')
    ]
    missing_packages: Annotated[
        list[str] | None,
        Field(description='Packages that are not importable', title='Missing Packages'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the reader', title='Name')
    ] = None
    reason: Annotated[
        str,
        Field(
            description='Verbatim import failure, including its install instruction',
            title='Reason',
        ),
    ]


class UpdateEvalRunRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    name: Annotated[
        str,
        Field(
            description='New name for the evaluation run',
            max_length=255,
            min_length=1,
            title='Name',
        ),
    ]


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    metadata: Annotated[
        dict[str, Any] | None, Field(description='Updated metadata', title='Metadata')
    ] = None
    session_name: Annotated[
        str | None, Field(description='Updated session name', title='Session Name')
    ] = None
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Updated session state', title='Session State'),
    ] = None
    summary: Annotated[
        dict[str, Any] | None, Field(description='Session summary', title='Summary')
    ] = None


class UserMemoryCreateSchema(BaseModel):
    """
    Define the payload expected for creating a new user memory
    """

    model_config = ConfigDict(
        extra='allow',
    )
    memory: Annotated[
        str,
        Field(
            description='Memory content text',
            max_length=5000,
            min_length=1,
            title='Memory',
        ),
    ]
    topics: Annotated[
        list[str] | None,
        Field(description='Topics or tags to categorize the memory', title='Topics'),
    ] = None
    user_id: Annotated[
        str | None, Field(description='User ID who owns this memory', title='User Id')
    ] = None


class UserMemorySchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None,
        Field(description='Agent ID associated with this memory', title='Agent Id'),
    ] = None
    memory: Annotated[str, Field(description='Memory content text', title='Memory')]
    memory_id: Annotated[
        str, Field(description='Unique identifier for the memory', title='Memory Id')
    ]
    team_id: Annotated[
        str | None,
        Field(description='Team ID associated with this memory', title='Team Id'),
    ] = None
    topics: Annotated[
        list[str] | None,
        Field(description='Topics or tags associated with the memory', title='Topics'),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(description='Timestamp when memory was last updated', title='Updated At'),
    ] = None
    user_id: Annotated[
        str | None, Field(description='User ID who owns this memory', title='User Id')
    ] = None


class UserStatsSchema(BaseModel):
    """
    Schema for user memory statistics
    """

    model_config = ConfigDict(
        extra='allow',
    )
    last_memory_updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Timestamp of the most recent memory update',
            title='Last Memory Updated At',
        ),
    ] = None
    total_memories: Annotated[
        int,
        Field(
            description='Total number of memories for this user',
            ge=0,
            title='Total Memories',
        ),
    ]
    user_id: Annotated[str, Field(description='User ID', title='User Id')]


class ValidationError(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    ctx: Annotated[dict[str, Any] | None, Field(title='Context')] = None
    input: Annotated[Any | None, Field(title='Input')] = None
    loc: Annotated[list[str | int], Field(title='Location')]
    msg: Annotated[str, Field(title='Message')]
    type: Annotated[str, Field(title='Error Type')]


class ValidationErrorDetail(BaseModel):
    """
    One field-level error inside a 422 body, matching FastAPI's default shape.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    loc: Annotated[
        list[str | int],
        Field(
            description="Path to the offending field, e.g. ['body', 'endpoint']",
            title='Loc',
        ),
    ]
    msg: Annotated[str, Field(description='Human-readable error message', title='Msg')]
    type: Annotated[
        str,
        Field(
            description="Error type identifier, e.g. 'value_error' or 'missing'",
            title='Type',
        ),
    ]


class ValidationErrorResponse(BaseModel):
    """
    422 body. Two runtime shapes share this status code, and the same endpoint can
    return either, so ``detail`` is typed as their union:

    - FastAPI's request-validation handler emits a **list** of field-level errors (built-in
      coercion errors and custom-validator ``ValueError``s alike).
    - A route that raises ``HTTPException(status_code=422, detail="...")`` for a semantic
      check (e.g. an invalid cron expression) emits a **string** through the HTTPException
      handler.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[
        str | list[ValidationErrorDetail],
        Field(
            description='A single message for an explicitly raised 422, or a list of field-level errors for a request-validation failure',
            title='Detail',
        ),
    ]


class VectorDbSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[
        str | None,
        Field(description='Description of the vector database', title='Description'),
    ] = None
    id: Annotated[
        str, Field(description='Unique identifier for the vector database', title='Id')
    ]
    name: Annotated[
        str | None, Field(description='Name of the vector database', title='Name')
    ] = None
    search_types: Annotated[
        list[str] | None,
        Field(
            description='List of supported search types (vector, keyword, hybrid)',
            title='Search Types',
        ),
    ] = None


class MaxResults(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description='The maximum number of results to return',
            ge=1,
            le=1000,
            title='Max Results',
        ),
    ]


class VectorSearchRequestSchema(BaseModel):
    """
    Schema for vector search request.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[
        str | None, Field(description='Database ID to search in', title='Db Id')
    ] = None
    filters: Annotated[
        dict[str, Any] | None,
        Field(description='Filters to apply to the search results', title='Filters'),
    ] = None
    knowledge_id: Annotated[
        str | None,
        Field(description='Knowledge base ID to search in', title='Knowledge Id'),
    ] = None
    max_results: Annotated[
        MaxResults | None,
        Field(
            description='The maximum number of results to return', title='Max Results'
        ),
    ] = None
    meta: Annotated[
        Meta | None,
        Field(
            description='Pagination metadata. Limit and page number to return a subset of results.'
        ),
    ] = None
    query: Annotated[str, Field(description='The search query text', title='Query')]
    search_type: Annotated[
        str | None,
        Field(
            description='The type of search to perform (vector, keyword, hybrid)',
            title='Search Type',
        ),
    ] = None
    vector_db_ids: Annotated[
        list[str] | None,
        Field(
            description='List of vector database IDs to search in',
            title='Vector Db Ids',
        ),
    ] = None


class RerankingScore(RootModel[float]):
    root: Annotated[
        float,
        Field(
            description='Reranking score for relevance',
            ge=-1.0,
            le=1.0,
            title='Reranking Score',
        ),
    ]


class Size(RootModel[int]):
    root: Annotated[
        int, Field(description='Size of the content in bytes', ge=0, title='Size')
    ]


class VectorSearchResult(BaseModel):
    """
    Schema for search result documents.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    content: Annotated[
        str, Field(description='Content text of the document', title='Content')
    ]
    content_id: Annotated[
        str | None, Field(description='ID of the source content', title='Content Id')
    ] = None
    content_origin: Annotated[
        str | None,
        Field(
            description='Origin URL or source of the content', title='Content Origin'
        ),
    ] = None
    id: Annotated[
        str | None,
        Field(
            description='Unique identifier for the search result document', title='Id'
        ),
    ] = None
    meta_data: Annotated[
        dict[str, Any] | None,
        Field(description='Metadata associated with the document', title='Meta Data'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the document', title='Name')
    ] = None
    reranking_score: Annotated[
        RerankingScore | None,
        Field(description='Reranking score for relevance', title='Reranking Score'),
    ] = None
    size: Annotated[
        Size | None, Field(description='Size of the content in bytes', title='Size')
    ] = None
    usage: Annotated[
        dict[str, Any] | None,
        Field(description='Usage statistics (e.g., token counts)', title='Usage'),
    ] = None


class WorkflowRunSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    audio: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Audio files included in the workflow', title='Audio'),
    ] = None
    cancellation_stage: Annotated[
        str | None,
        Field(
            description='For CANCELLED runs, where the run was when it was cancelled: PENDING, EXECUTING, PAUSED. Absent means unknown.',
            title='Cancellation Stage',
        ),
    ] = None
    citations: Annotated[
        dict[str, Any] | None,
        Field(
            description='Citations from the model (e.g., from Gemini grounding/search)',
            title='Citations',
        ),
    ] = None
    content: Annotated[
        str | dict[str, Any] | None,
        Field(description='Output content from the workflow', title='Content'),
    ] = None
    content_type: Annotated[
        str | None, Field(description='Type of content returned', title='Content Type')
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Run creation timestamp', title='Created At'),
    ] = None
    events: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Events generated during the workflow', title='Events'),
    ] = None
    files: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Files included in the workflow', title='Files'),
    ] = None
    images: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Images included in the workflow', title='Images'),
    ] = None
    metrics: Annotated[
        dict[str, Any] | None,
        Field(description='Performance and usage metrics', title='Metrics'),
    ] = None
    pause_kind: Annotated[
        str | None,
        Field(
            description="Kind of HITL pause: 'step' or 'executor'", title='Pause Kind'
        ),
    ] = None
    paused_step_index: Annotated[
        int | None,
        Field(
            description='Index of the step that caused the pause',
            title='Paused Step Index',
        ),
    ] = None
    paused_step_name: Annotated[
        str | None,
        Field(
            description='Name of the step that caused the pause',
            title='Paused Step Name',
        ),
    ] = None
    reasoning_content: Annotated[
        str | None,
        Field(
            description='Reasoning content if reasoning was enabled',
            title='Reasoning Content',
        ),
    ] = None
    reasoning_messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Reasoning process messages', title='Reasoning Messages'),
    ] = None
    reasoning_steps: Annotated[
        list[dict[str, Any]] | None,
        Field(description='List of reasoning steps', title='Reasoning Steps'),
    ] = None
    references: Annotated[
        list[dict[str, Any]] | None,
        Field(description='References cited in the workflow', title='References'),
    ] = None
    response_audio: Annotated[
        dict[str, Any] | None,
        Field(description='Audio response if generated', title='Response Audio'),
    ] = None
    run_id: Annotated[
        str, Field(description='Unique identifier for the workflow run', title='Run Id')
    ]
    run_input: Annotated[
        str | None,
        Field(description='Input provided to the workflow', title='Run Input'),
    ] = None
    status: Annotated[
        str | None, Field(description='Status of the workflow run', title='Status')
    ] = None
    step_executor_runs: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Executor runs for each step', title='Step Executor Runs'),
    ] = None
    step_requirements: Annotated[
        list[dict[str, Any]] | None,
        Field(
            description='HITL step requirements (resolved state for historical display)',
            title='Step Requirements',
        ),
    ] = None
    step_results: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Results from each workflow step', title='Step Results'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the run', title='User Id'),
    ] = None
    videos: Annotated[
        list[dict[str, Any]] | None,
        Field(description='Videos included in the workflow', title='Videos'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(description='Workflow ID that was executed', title='Workflow Id'),
    ] = None


class WorkflowSessionDetailSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Session creation timestamp', title='Created At'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    session_data: Annotated[
        dict[str, Any] | None,
        Field(description='Complete session data', title='Session Data'),
    ] = None
    session_id: Annotated[
        str, Field(description='Unique session identifier', title='Session Id')
    ]
    session_name: Annotated[
        str, Field(description='Human-readable session name', title='Session Name')
    ]
    session_state: Annotated[
        dict[str, Any] | None,
        Field(description='Current workflow state', title='Session State'),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(description='Last update timestamp', title='Updated At'),
    ] = None
    user_id: Annotated[
        str | None,
        Field(description='User ID associated with the session', title='User Id'),
    ] = None
    workflow_data: Annotated[
        dict[str, Any] | None,
        Field(description='Workflow-specific data', title='Workflow Data'),
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(description='Workflow ID used in this session', title='Workflow Id'),
    ] = None
    workflow_name: Annotated[
        str | None, Field(description='Name of the workflow', title='Workflow Name')
    ] = None


class WorkflowSummaryResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    current_version: Annotated[
        int | None,
        Field(description='Current published version number', title='Current Version'),
    ] = None
    db_id: Annotated[
        str | None, Field(description='Database identifier', title='Db Id')
    ] = None
    description: Annotated[
        str | None,
        Field(description='Description of the workflow', title='Description'),
    ] = None
    factory_input_schema: Annotated[
        dict[str, Any] | None,
        Field(
            description='JSON Schema for factory_input', title='Factory Input Schema'
        ),
    ] = None
    id: Annotated[
        str | None, Field(description='Unique identifier for the workflow', title='Id')
    ] = None
    is_component: Annotated[
        bool | None,
        Field(
            description='Whether this workflow was created via Builder',
            title='Is Component',
        ),
    ] = False
    is_factory: Annotated[
        bool | None,
        Field(description='Whether this workflow is a factory', title='Is Factory'),
    ] = False
    name: Annotated[
        str | None, Field(description='Name of the workflow', title='Name')
    ] = None
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False
    stage: Annotated[
        str | None,
        Field(
            description='Stage of the loaded config (draft/published)', title='Stage'
        ),
    ] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    current_version: Annotated[int | None, Field(title='Current Version')] = None
    db_id: Annotated[str | None, Field(title='Db Id')] = None
    default_tools: Annotated[dict[str, Any] | None, Field(title='Default Tools')] = None
    description: Annotated[str | None, Field(title='Description')] = None
    extra_messages: Annotated[dict[str, Any] | None, Field(title='Extra Messages')] = (
        None
    )
    factory_input_schema: Annotated[
        dict[str, Any] | None, Field(title='Factory Input Schema')
    ] = None
    filesystem: Annotated[bool | None, Field(title='Filesystem')] = False
    id: Annotated[str | None, Field(title='Id')] = None
    input_schema: Annotated[dict[str, Any] | None, Field(title='Input Schema')] = None
    introduction: Annotated[str | None, Field(title='Introduction')] = None
    is_component: Annotated[bool | None, Field(title='Is Component')] = False
    is_factory: Annotated[bool | None, Field(title='Is Factory')] = False
    knowledge: Annotated[dict[str, Any] | None, Field(title='Knowledge')] = None
    memory: Annotated[dict[str, Any] | None, Field(title='Memory')] = None
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    model: ModelResponse | None = None
    name: Annotated[str | None, Field(title='Name')] = None
    reasoning: Annotated[dict[str, Any] | None, Field(title='Reasoning')] = None
    response_settings: Annotated[
        dict[str, Any] | None, Field(title='Response Settings')
    ] = None
    role: Annotated[str | None, Field(title='Role')] = None
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False
    sessions: Annotated[dict[str, Any] | None, Field(title='Sessions')] = None
    stage: Annotated[str | None, Field(title='Stage')] = None
    streaming: Annotated[dict[str, Any] | None, Field(title='Streaming')] = None
    system_message: Annotated[dict[str, Any] | None, Field(title='System Message')] = (
        None
    )
    tools: Annotated[dict[str, Any] | None, Field(title='Tools')] = None


class AgentSummaryResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[
        str | None, Field(description='Database identifier', title='Db Id')
    ] = None
    description: Annotated[
        str | None, Field(description='Description of the agent', title='Description')
    ] = None
    id: Annotated[
        str | None, Field(description='Unique identifier for the agent', title='Id')
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    model: Annotated[Model | None, Field(description='Model used by the agent')] = None
    name: Annotated[
        str | None, Field(description='Name of the agent', title='Name')
    ] = None
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False


class ApprovalResponse(BaseModel):
    """
    Response model for a single approval.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[str | None, Field(title='Agent Id')] = None
    approval_type: Annotated[str | None, Field(title='Approval Type')] = None
    context: Annotated[dict[str, Any] | None, Field(title='Context')] = None
    created_at: Annotated[int | None, Field(title='Created At')] = None
    expires_at: Annotated[int | None, Field(title='Expires At')] = None
    id: Annotated[str, Field(title='Id')]
    pause_type: Annotated[str | None, Field(title='Pause Type')] = None
    requirements: Annotated[
        list[dict[str, Any]] | None, Field(title='Requirements')
    ] = None
    resolution_data: Annotated[
        dict[str, Any] | None, Field(title='Resolution Data')
    ] = None
    resolved_at: Annotated[int | None, Field(title='Resolved At')] = None
    resolved_by: Annotated[str | None, Field(title='Resolved By')] = None
    run_id: Annotated[str, Field(title='Run Id')]
    run_status: RunStatus | None = None
    schedule_id: Annotated[str | None, Field(title='Schedule Id')] = None
    schedule_run_id: Annotated[str | None, Field(title='Schedule Run Id')] = None
    session_id: Annotated[str, Field(title='Session Id')]
    source_name: Annotated[str | None, Field(title='Source Name')] = None
    source_type: Annotated[str, Field(title='Source Type')]
    status: Annotated[str, Field(title='Status')]
    team_id: Annotated[str | None, Field(title='Team Id')] = None
    tool_args: Annotated[dict[str, Any] | None, Field(title='Tool Args')] = None
    tool_name: Annotated[str | None, Field(title='Tool Name')] = None
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None
    workflow_id: Annotated[str | None, Field(title='Workflow Id')] = None


class CompanySectionConfig(BaseModel):
    """
    Company database and table configuration exposed to clients.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigCompanyDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class ComponentCreate(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    component_id: Annotated[
        str | None,
        Field(
            description='Unique identifier for the entity. Auto-generated from name if not provided.',
            title='Component Id',
        ),
    ] = None
    component_type: Annotated[
        ComponentType, Field(description='Type of entity: agent, team, or workflow')
    ]
    config: Annotated[
        dict[str, Any] | None,
        Field(description='Optional configuration', title='Config'),
    ] = None
    description: Annotated[
        str | None, Field(description='Optional description', title='Description')
    ] = None
    label: Annotated[
        str | None, Field(description="Optional label (e.g., 'stable')", title='Label')
    ] = None
    metadata: Annotated[
        dict[str, Any] | None, Field(description='Optional metadata', title='Metadata')
    ] = None
    name: Annotated[str, Field(description='Display name', title='Name')]
    notes: Annotated[str | None, Field(description='Optional notes', title='Notes')] = (
        None
    )
    set_current: Annotated[
        bool | None, Field(description='Set as current version', title='Set Current')
    ] = True
    stage: Annotated[
        str | None, Field(description="Stage: 'draft' or 'published'", title='Stage')
    ] = 'draft'


class ComponentDeleteRequest(BaseModel):
    """
    Body for delete. Optional: a bodyless DELETE keeps working.

    Delete also accepts the guard as an ``expected_current_version`` query
    param; this shape exists so the guard reads the same as on every other
    guarded component route instead of being silently ignored here.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    guard: Annotated[
        ComponentGuard | None, Field(description='Optional compare-and-set guard')
    ] = None


class ComponentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    component_id: Annotated[str, Field(title='Component Id')]
    component_type: ComponentType
    created_at: Annotated[int, Field(title='Created At')]
    current_version: Annotated[int | None, Field(title='Current Version')] = None
    deleted_at: Annotated[int | None, Field(title='Deleted At')] = None
    description: Annotated[str | None, Field(title='Description')] = None
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    name: Annotated[str | None, Field(title='Name')] = None
    updated_at: Annotated[int | None, Field(title='Updated At')] = None
    user_id: Annotated[str | None, Field(title='User Id')] = None


class ConfigResponseSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    chunkers: Annotated[
        dict[str, ChunkerSchema] | None,
        Field(description='Available chunking strategies', title='Chunkers'),
    ] = None
    filters: Annotated[
        list[str] | None, Field(description='Available filter tags', title='Filters')
    ] = None
    readers: Annotated[
        dict[str, ReaderSchema] | None,
        Field(description='Available content readers', title='Readers'),
    ] = None
    readersForType: Annotated[
        dict[str, list[str]] | None,
        Field(
            description='Mapping of content types to reader IDs', title='Readersfortype'
        ),
    ] = None
    remote_content_sources: Annotated[
        list[RemoteContentSourceSchema] | None,
        Field(
            description='Configured remote content sources (S3, GCS, SharePoint, GitHub)',
            title='Remote Content Sources',
        ),
    ] = None
    unavailable_chunkers: Annotated[
        dict[str, UnavailableChunkerSchema] | None,
        Field(
            description='Chunking strategies that are not usable in this install, and the packages they need',
            title='Unavailable Chunkers',
        ),
    ] = None
    unavailable_readers: Annotated[
        dict[str, UnavailableReaderSchema] | None,
        Field(
            description='Readers that are not usable in this install, and the packages they need',
            title='Unavailable Readers',
        ),
    ] = None
    vector_dbs: Annotated[
        list[VectorDbSchema] | None,
        Field(description='Configured vector databases', title='Vector Dbs'),
    ] = None


class ContentResponseSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    access_count: Annotated[
        AccessCount | None,
        Field(
            description='Number of times content has been accessed',
            title='Access Count',
        ),
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Timestamp when content was created', title='Created At'),
    ] = None
    description: Annotated[
        str | None, Field(description='Description of the content', title='Description')
    ] = None
    id: Annotated[
        str, Field(description='Unique identifier for the content', title='Id')
    ]
    linked_to: Annotated[
        str | None,
        Field(description='ID of related content if linked', title='Linked To'),
    ] = None
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata as key-value pairs', title='Metadata'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the content', title='Name')
    ] = None
    size: Annotated[
        str | None, Field(description='Size of the content in bytes', title='Size')
    ] = None
    status: Annotated[
        ContentStatus | None, Field(description='Processing status of the content')
    ] = None
    status_message: Annotated[
        str | None,
        Field(description='Status message or error details', title='Status Message'),
    ] = None
    type: Annotated[
        str | None, Field(description='MIME type of the content', title='Type')
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Timestamp when content was last updated', title='Updated At'
        ),
    ] = None


class DatabaseConfigEvalsDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: EvalsDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DatabaseConfigLearningDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: LearningDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DatabaseConfigMemoryDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: MemoryDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DatabaseConfigMetricsDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: MetricsDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DatabaseConfigSessionDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: SessionDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DatabaseConfigTracesDomainConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: TracesDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = None


class DeleteSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    session_ids: Annotated[
        list[str],
        Field(
            description='List of session IDs to delete',
            min_length=1,
            title='Session Ids',
        ),
    ]
    session_types: Annotated[
        list[SessionType],
        Field(
            description='Types of sessions to delete',
            min_length=1,
            title='Session Types',
        ),
    ]


class EvalRunInput(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    additional_context: Annotated[
        str | None,
        Field(
            description='Additional context for the evaluation',
            title='Additional Context',
        ),
    ] = None
    additional_guidelines: Annotated[
        str | None,
        Field(
            description='Additional guidelines for the evaluation',
            title='Additional Guidelines',
        ),
    ] = None
    agent_id: Annotated[
        str | None, Field(description='Agent ID to evaluate', title='Agent Id')
    ] = None
    allow_additional_tool_calls: Annotated[
        bool | None,
        Field(
            description='When True, tool calls not in expected_tool_calls are allowed (subset matching)',
            title='Allow Additional Tool Calls',
        ),
    ] = False
    criteria: Annotated[
        str | None,
        Field(
            description='Evaluation criteria for agent-as-judge evaluation',
            title='Criteria',
        ),
    ] = None
    eval_type: Annotated[
        EvalType,
        Field(
            description='Type of evaluation to run (accuracy, performance, or reliability)'
        ),
    ]
    expected_output: Annotated[
        str | None,
        Field(
            description='Expected output for accuracy evaluation',
            title='Expected Output',
        ),
    ] = None
    expected_tool_call_arguments: Annotated[
        dict[str, dict[str, Any] | list[dict[str, Any]]] | None,
        Field(
            description='Expected arguments for specific tool calls, e.g. {"tool_name": {"arg_name": "expected_value"}} or {"tool_name": [{"arg_name": "val1"}, {"arg_name": "val2"}]}',
            title='Expected Tool Call Arguments',
        ),
    ] = None
    expected_tool_calls: Annotated[
        list[str] | None,
        Field(
            description='Expected tool calls for reliability evaluation',
            title='Expected Tool Calls',
        ),
    ] = None
    input: Annotated[
        str,
        Field(
            description='Input text/query for the evaluation',
            min_length=1,
            title='Input',
        ),
    ]
    model_id: Annotated[
        str | None,
        Field(description='Model ID to use for evaluation', title='Model Id'),
    ] = None
    model_provider: Annotated[
        str | None, Field(description='Model provider name', title='Model Provider')
    ] = None
    name: Annotated[
        str | None, Field(description='Name for this evaluation run', title='Name')
    ] = None
    num_iterations: Annotated[
        int | None,
        Field(
            description='Number of times to run the evaluation',
            ge=1,
            le=100,
            title='Num Iterations',
        ),
    ] = 1
    scoring_strategy: Annotated[
        ScoringStrategy | None,
        Field(
            description="Scoring strategy: 'numeric' (1-10 with threshold) or 'binary' (PASS/FAIL)",
            title='Scoring Strategy',
        ),
    ] = 'binary'
    team_id: Annotated[
        str | None, Field(description='Team ID to evaluate', title='Team Id')
    ] = None
    threshold: Annotated[
        Threshold | None,
        Field(
            description='Score threshold for pass/fail (1-10), only used with numeric scoring',
            title='Threshold',
            validate_default=True,
        ),
    ] = 7
    warmup_runs: Annotated[
        int | None,
        Field(
            description='Number of warmup runs before measuring performance',
            ge=0,
            le=10,
            title='Warmup Runs',
        ),
    ] = 0


class EvalSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None, Field(description='Agent ID that was evaluated', title='Agent Id')
    ] = None
    created_at: Annotated[
        AwareDatetime | None,
        Field(description='Timestamp when evaluation was created', title='Created At'),
    ] = None
    eval_data: Annotated[
        dict[str, Any],
        Field(description='Evaluation results and metrics', title='Eval Data'),
    ]
    eval_input: Annotated[
        dict[str, Any] | None,
        Field(
            description='Input parameters used for the evaluation', title='Eval Input'
        ),
    ] = None
    eval_type: Annotated[
        EvalType,
        Field(description='Type of evaluation (accuracy, performance, or reliability)'),
    ]
    evaluated_component_name: Annotated[
        str | None,
        Field(
            description='Name of the evaluated component',
            title='Evaluated Component Name',
        ),
    ] = None
    id: Annotated[
        str, Field(description='Unique identifier for the evaluation run', title='Id')
    ]
    model_id: Annotated[
        str | None, Field(description='Model ID used in evaluation', title='Model Id')
    ] = None
    model_provider: Annotated[
        str | None, Field(description='Model provider name', title='Model Provider')
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the evaluation run', title='Name')
    ] = None
    team_id: Annotated[
        str | None, Field(description='Team ID that was evaluated', title='Team Id')
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Timestamp when evaluation was last updated', title='Updated At'
        ),
    ] = None
    user_id: Annotated[
        str | None, Field(description='Owner of the evaluation run', title='User Id')
    ] = None
    workflow_id: Annotated[
        str | None,
        Field(description='Workflow ID that was evaluated', title='Workflow Id'),
    ] = None


class EvalsConfig(BaseModel):
    """
    Configuration for the Evals domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[list[DatabaseConfigEvalsDomainConfig] | None, Field(title='Dbs')] = (
        None
    )
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class FileSystemConfig(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    namespaces: Annotated[
        list[FileSystemNamespace] | None,
        Field(
            description='Filesystem namespaces with their backend details, limits, and linked agents',
            title='Namespaces',
        ),
    ] = None


class FileSystemListResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_ids: Annotated[list[str], Field(title='Agent Ids')]
    directory: Annotated[str, Field(title='Directory')]
    entries: Annotated[list[FileSystemEntry], Field(title='Entries')]
    meta: PaginationInfo
    namespace: Annotated[str, Field(title='Namespace')]
    usage: FileSystemUsage


class FileSystemSearchResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent_ids: Annotated[list[str], Field(title='Agent Ids')]
    directory: Annotated[str, Field(title='Directory')]
    entries: Annotated[list[FileSystemSearchEntry], Field(title='Entries')]
    meta: PaginationInfo
    namespace: Annotated[str, Field(title='Namespace')]
    query: Annotated[str, Field(title='Query')]


class FileSystemTableResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    entries: Annotated[list[FileSystemTableEntry], Field(title='Entries')]
    meta: PaginationInfo


class HTTPValidationError(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    detail: Annotated[list[ValidationError] | None, Field(title='Detail')] = None


class KnowledgeDatabaseConfig(BaseModel):
    """
    Configuration for a knowledge database with its tables
    """

    model_config = ConfigDict(
        extra='allow',
    )
    db_id: Annotated[str, Field(title='Db Id')]
    domain_config: KnowledgeDomainConfig | None = None
    tables: Annotated[list[str] | None, Field(title='Tables')] = []


class LearningConfig(BaseModel):
    """
    Configuration for the Learning domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigLearningDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class McpInfo(BaseModel):
    """
    MCP server availability for the /info endpoint.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    enabled: Annotated[
        bool | None,
        Field(
            description='Whether the MCP server is enabled on this OS instance',
            title='Enabled',
        ),
    ] = False
    oauth: Annotated[
        McpOAuthInfo | None,
        Field(
            description='OAuth discovery details when the MCP endpoint is OAuth-protected, null otherwise'
        ),
    ] = None
    path: Annotated[
        str | None,
        Field(
            description='Path where the MCP server is mounted, null when disabled',
            title='Path',
        ),
    ] = None
    tool_run_endpoint: Annotated[
        bool | None,
        Field(
            description='Whether this deployment serves the plain-HTTP tool runner at `{path}/server/tools/{tool_name}/run`. False both when the MCP server is off and when it is on with `MCPConfig(tool_run_endpoint=False)`, so a client can tell upfront whether running a tool is possible instead of discovering it on the call.',
            title='Tool Run Endpoint',
        ),
    ] = False


class MemoryConfig(BaseModel):
    """
    Configuration for the Memory domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigMemoryDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class MetricsConfig(BaseModel):
    """
    Configuration for the Metrics domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigMetricsDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class OptimizeMemoriesResponse(BaseModel):
    """
    Schema for memory optimization response
    """

    model_config = ConfigDict(
        extra='allow',
    )
    memories: Annotated[
        list[UserMemorySchema],
        Field(description='List of optimized memory objects', title='Memories'),
    ]
    memories_after: Annotated[
        int,
        Field(
            description='Number of memories after optimization',
            ge=0,
            title='Memories After',
        ),
    ]
    memories_before: Annotated[
        int,
        Field(
            description='Number of memories before optimization',
            ge=0,
            title='Memories Before',
        ),
    ]
    reduction_percentage: Annotated[
        float,
        Field(
            description='Percentage of token reduction achieved',
            ge=0.0,
            le=100.0,
            title='Reduction Percentage',
        ),
    ]
    tokens_after: Annotated[
        int,
        Field(description='Token count after optimization', ge=0, title='Tokens After'),
    ]
    tokens_before: Annotated[
        int,
        Field(
            description='Token count before optimization', ge=0, title='Tokens Before'
        ),
    ]
    tokens_saved: Annotated[
        int,
        Field(
            description='Number of tokens saved through optimization',
            ge=0,
            title='Tokens Saved',
        ),
    ]


class PaginatedResponseApprovalResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ApprovalResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseComponentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ComponentResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseContentResponseSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ContentResponseSchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseEvalSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[EvalSchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseLearningResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[LearningResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseLearningUserStats(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[LearningUserStats],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseQueueJobSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[QueueJobSchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseScheduleResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ScheduleResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseScheduleRunResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ScheduleRunResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseServiceAccountResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[ServiceAccountResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseSessionSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[SessionSchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseTraceSessionStats(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[TraceSessionStats],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseTraceSummary(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[TraceSummary],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseUserMemorySchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[UserMemorySchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseUserStatsSchema(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[UserStatsSchema],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseVectorSearchResult(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[VectorSearchResult],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class RegistryContentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    description: Annotated[str | None, Field(title='Description')] = None
    id: Annotated[str | None, Field(title='Id')] = None
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    name: Annotated[str, Field(title='Name')]
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False
    type: RegistryResourceType


class SessionConfig(BaseModel):
    """
    Configuration for the Session domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigSessionDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class SessionSearchRequest(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    filter: Annotated[dict[str, Any] | None, Field(title='Filter')] = None
    limit: Annotated[int | None, Field(ge=1, le=100, title='Limit')] = 20
    page: Annotated[int | None, Field(ge=1, title='Page')] = 1
    session_type: SessionType | None = None
    sort_by: Annotated[SortBy | None, Field(title='Sort By')] = 'created_at'
    sort_order: Annotated[SortOrder | None, Field(title='Sort Order')] = 'desc'


class SourceFilesResponseSchema(BaseModel):
    """
    Response schema for listing files in a content source.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    files: Annotated[
        list[SourceFileSchema] | None,
        Field(description='List of files at this level', title='Files'),
    ] = None
    folders: Annotated[
        list[SourceFolderSchema] | None,
        Field(description='Subfolders at this level', title='Folders'),
    ] = None
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]
    prefix: Annotated[
        str | None, Field(description='Prefix filter that was applied', title='Prefix')
    ] = None
    source_id: Annotated[
        str, Field(description='ID of the content source', title='Source Id')
    ]
    source_name: Annotated[
        str, Field(description='Name of the content source', title='Source Name')
    ]


class TeamResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    current_version: Annotated[int | None, Field(title='Current Version')] = None
    db_id: Annotated[str | None, Field(title='Db Id')] = None
    default_tools: Annotated[dict[str, Any] | None, Field(title='Default Tools')] = None
    description: Annotated[str | None, Field(title='Description')] = None
    factory_input_schema: Annotated[
        dict[str, Any] | None, Field(title='Factory Input Schema')
    ] = None
    id: Annotated[str | None, Field(title='Id')] = None
    input_schema: Annotated[dict[str, Any] | None, Field(title='Input Schema')] = None
    introduction: Annotated[str | None, Field(title='Introduction')] = None
    is_component: Annotated[bool | None, Field(title='Is Component')] = False
    is_factory: Annotated[bool | None, Field(title='Is Factory')] = False
    knowledge: Annotated[dict[str, Any] | None, Field(title='Knowledge')] = None
    members: Annotated[
        list[AgentResponse | TeamResponse] | None, Field(title='Members')
    ] = None
    memory: Annotated[dict[str, Any] | None, Field(title='Memory')] = None
    metadata: Annotated[dict[str, Any] | None, Field(title='Metadata')] = None
    mode: Annotated[str | None, Field(title='Mode')] = None
    model: ModelResponse | None = None
    name: Annotated[str | None, Field(title='Name')] = None
    reasoning: Annotated[dict[str, Any] | None, Field(title='Reasoning')] = None
    response_settings: Annotated[
        dict[str, Any] | None, Field(title='Response Settings')
    ] = None
    role: Annotated[str | None, Field(title='Role')] = None
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False
    sessions: Annotated[dict[str, Any] | None, Field(title='Sessions')] = None
    stage: Annotated[str | None, Field(title='Stage')] = None
    streaming: Annotated[dict[str, Any] | None, Field(title='Streaming')] = None
    system_message: Annotated[dict[str, Any] | None, Field(title='System Message')] = (
        None
    )
    tools: Annotated[dict[str, Any] | None, Field(title='Tools')] = None


class TraceDetail(BaseModel):
    """
    Detailed trace information with hierarchical span tree
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_id: Annotated[
        str | None, Field(description='Associated agent ID', title='Agent Id')
    ] = None
    created_at: Annotated[
        AwareDatetime,
        Field(
            description='Time when trace was created (Pydantic auto-serializes to ISO 8601)',
            title='Created At',
        ),
    ]
    duration: Annotated[
        str, Field(description='Human-readable total duration', title='Duration')
    ]
    end_time: Annotated[
        AwareDatetime,
        Field(
            description='Trace end time (Pydantic auto-serializes to ISO 8601)',
            title='End Time',
        ),
    ]
    error: Annotated[
        str | None, Field(description='Error message if status is ERROR', title='Error')
    ] = None
    error_count: Annotated[
        int, Field(description='Number of spans with errors', title='Error Count')
    ]
    input: Annotated[
        str | None, Field(description='Input to the agent/workflow', title='Input')
    ] = None
    name: Annotated[
        str, Field(description='Trace name (usually root span name)', title='Name')
    ]
    output: Annotated[
        str | None, Field(description='Output from the agent/workflow', title='Output')
    ] = None
    run_id: Annotated[
        str | None, Field(description='Associated run ID', title='Run Id')
    ] = None
    session_id: Annotated[
        str | None, Field(description='Associated session ID', title='Session Id')
    ] = None
    start_time: Annotated[
        AwareDatetime,
        Field(
            description='Trace start time (Pydantic auto-serializes to ISO 8601)',
            title='Start Time',
        ),
    ]
    status: Annotated[
        str, Field(description='Overall status (OK, ERROR)', title='Status')
    ]
    team_id: Annotated[
        str | None, Field(description='Associated team ID', title='Team Id')
    ] = None
    total_spans: Annotated[
        int,
        Field(description='Total number of spans in this trace', title='Total Spans'),
    ]
    trace_id: Annotated[
        str, Field(description='Unique trace identifier', title='Trace Id')
    ]
    tree: Annotated[
        list[TraceNode],
        Field(description='Hierarchical tree of spans (root nodes)', title='Tree'),
    ]
    user_id: Annotated[
        str | None, Field(description='Associated user ID', title='User Id')
    ] = None
    workflow_id: Annotated[
        str | None, Field(description='Associated workflow ID', title='Workflow Id')
    ] = None


class TracesConfig(BaseModel):
    """
    Configuration for the Traces domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[
        list[DatabaseConfigTracesDomainConfig] | None, Field(title='Dbs')
    ] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    agent: Annotated[
        AgentResponse | None, Field(description='Agent configuration if used')
    ] = None
    current_version: Annotated[
        int | None,
        Field(description='Current published version number', title='Current Version'),
    ] = None
    db_id: Annotated[
        str | None, Field(description='Database identifier', title='Db Id')
    ] = None
    description: Annotated[
        str | None,
        Field(description='Description of the workflow', title='Description'),
    ] = None
    factory_input_schema: Annotated[
        dict[str, Any] | None,
        Field(
            description='JSON Schema for factory_input', title='Factory Input Schema'
        ),
    ] = None
    id: Annotated[
        str | None, Field(description='Unique identifier for the workflow', title='Id')
    ] = None
    input_schema: Annotated[
        dict[str, Any] | None,
        Field(description='Input schema for the workflow', title='Input Schema'),
    ] = None
    is_component: Annotated[
        bool | None,
        Field(
            description='Whether this workflow was created via Builder',
            title='Is Component',
        ),
    ] = False
    is_factory: Annotated[
        bool | None,
        Field(description='Whether this workflow is a factory', title='Is Factory'),
    ] = False
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description='Additional metadata', title='Metadata'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the workflow', title='Name')
    ] = None
    sandboxed: Annotated[bool | None, Field(title='Sandboxed')] = False
    stage: Annotated[
        str | None,
        Field(
            description='Stage of the loaded config (draft/published)', title='Stage'
        ),
    ] = None
    steps: Annotated[
        list[dict[str, Any]] | None,
        Field(description='List of workflow steps', title='Steps'),
    ] = None
    team: Annotated[
        TeamResponse | None, Field(description='Team configuration if used')
    ] = None
    workflow_agent: Annotated[
        bool | None,
        Field(
            description='Whether this workflow uses a WorkflowAgent',
            title='Workflow Agent',
        ),
    ] = False


class InfoResponse(BaseModel):
    """
    Response schema for the /info endpoint returning lightweight OS metadata.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    agent_count: Annotated[
        int | None,
        Field(description='Number of agents registered in the OS', title='Agent Count'),
    ] = 0
    agno_version: Annotated[
        str, Field(description='Version of the agno framework', title='Agno Version')
    ]
    auth_mode: Annotated[
        AuthMode | None,
        Field(
            description='Authentication mode enforced on the REST/WS plane of this OS instance. MCP OAuth, when enabled, is described separately under `mcp.oauth`.',
            title='Auth Mode',
        ),
    ] = 'none'
    mcp: Annotated[
        McpInfo | None,
        Field(description='MCP server availability for this OS instance'),
    ] = None
    name: Annotated[
        str | None, Field(description='Name of the OS instance', title='Name')
    ] = None
    os_id: Annotated[
        str, Field(description='Unique identifier for the OS instance', title='Os Id')
    ]
    os_version: Annotated[
        str, Field(description='Version of this AgentOS instance', title='Os Version')
    ]
    team_count: Annotated[
        int | None,
        Field(description='Number of teams registered in the OS', title='Team Count'),
    ] = 0
    user_isolation: Annotated[
        bool | None,
        Field(
            description="Whether per-user data isolation is switched on for this OS instance. Read it together with `auth_mode`: under `jwt` the token names the user, so a client sends nothing extra. Under `none` or `security_key` the OS cannot tell who a request is for, so a client that wants each user to see only their own data sends that user's id as `user_id` on every request, reads included, not only on runs.",
            title='User Isolation',
        ),
    ] = False
    workflow_count: Annotated[
        int | None,
        Field(
            description='Number of workflows registered in the OS',
            title='Workflow Count',
        ),
    ] = 0


class KnowledgeConfig(BaseModel):
    """
    Configuration for the Knowledge domain of the AgentOS
    """

    model_config = ConfigDict(
        extra='allow',
    )
    dbs: Annotated[list[KnowledgeDatabaseConfig] | None, Field(title='Dbs')] = None
    display_name: Annotated[str | None, Field(title='Display Name')] = None
    knowledge_instances: Annotated[
        list[KnowledgeInstanceConfig] | None, Field(title='Knowledge Instances')
    ] = None


class PaginatedResponseRegistryContentResponse(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[RegistryContentResponse],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


class PaginatedResponseTraceDetail(BaseModel):
    model_config = ConfigDict(
        extra='allow',
    )
    data: Annotated[
        list[TraceDetail],
        Field(description='List of items for the current page', title='Data'),
    ]
    meta: Annotated[PaginationInfo, Field(description='Pagination metadata')]


TraceNode.model_rebuild()
TeamResponse.model_rebuild()
