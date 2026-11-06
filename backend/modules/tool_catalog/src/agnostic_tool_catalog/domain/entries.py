"""Tool catalog entries: approved MCP servers and configured Agno toolkits, and the rules they follow.

An entry is published at one of three levels:

- **org**: set up by org owners and administrators, offered to everyone;
- **team**: set up by the owners of a directory group, offered to that group (and to org owners and administrators);
- **custom**: set up by a builder from the full list of Agno toolkits (or an MCP server URL), offered to its author
  and the group that owns the component it was made for.

Every entry gets a level-qualified registry name (``org-linear``, ``team-data-linear``, ``custom-7k2p9q-linear``),
so the same toolkit offered at two levels never collides on a runtime and every block shows which one it is.

No secret is ever stored: a credential is the *name* of an environment variable on the runtime
(``{"env": "LINEAR_TOKEN", "format": "Bearer {}"}``), which the bridge reads when it builds the tool.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlsplit

type Level = Literal["org", "team", "custom"]
type Kind = Literal["mcp", "toolkit"]
type Transport = Literal["streamable-http", "sse", "stdio"]
type EntryStatus = Literal["active", "disabled"]

LEVELS: tuple[Level, ...] = ("org", "team", "custom")
KINDS: tuple[Kind, ...] = ("mcp", "toolkit")
TRANSPORTS: tuple[Transport, ...] = ("streamable-http", "sse", "stdio")
LEVEL_LABELS: dict[Level, str] = {"org": "Organization", "team": "Team", "custom": "Custom"}

MAX_REGISTRY_NAME = 63
MAX_TIMEOUT_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 10

_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_PREFIX = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_CREDENTIAL = re.compile(
    r"(auth|token|key|secret|password|passwd|cookie|credential|session|signature|sig)", re.IGNORECASE
)
_COMMAND = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


class InvalidEntryError(ValueError):
    """An entry that breaks a rule; the message says what to change."""


@dataclass(frozen=True, slots=True)
class EnvRef:
    env: str
    format: str | None = None
    """``Bearer {}``: the value is put where ``{}`` is."""


@dataclass(frozen=True, slots=True)
class ToolkitParamInfo:
    name: str
    type: str
    required: bool
    secret: bool
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolkitInfo:
    """What the rules need to know about an Agno toolkit (from the shared toolkit list)."""

    key: str
    label: str
    local: bool
    params: tuple[ToolkitParamInfo, ...]

    def param(self, name: str) -> ToolkitParamInfo | None:
        return next((param for param in self.params if param.name == name), None)


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    slug: str
    registry_name: str
    level: Level
    owner_group_id: str | None
    display_name: str
    description: str
    icon: str | None
    kind: Kind
    transport: Transport | None
    toolkit_key: str | None
    config: dict[str, Any]
    """Cleaned by :func:`clean_mcp` or :func:`clean_toolkit`; env refs as ``{"env": ..., "format": ...}``."""
    requires_confirmation_tools: tuple[str, ...]
    instance_ids: tuple[str, ...]
    """Empty: every instance."""
    status: EntryStatus
    version: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    local: bool = False
    """Runs commands on the runtime (stdio, or a shell/python/file toolkit): privileged and opt-in per runtime."""

    def applies_to(self, instance_id: str) -> bool:
        return not self.instance_ids or instance_id in self.instance_ids

    @property
    def same_as_key(self) -> str:
        """What makes two entries "the same tool" for the "already offered" hint: toolkit key or server URL."""
        if self.kind == "toolkit":
            return f"toolkit:{self.toolkit_key}"
        url = str(self.config.get("url") or "")
        return f"mcp:{url.rstrip('/')}" if url else f"mcp:{self.config.get('command')}"


@dataclass(frozen=True, slots=True)
class Viewer:
    """Who is looking: their id, the groups they're in and own, and whether they manage the whole catalog."""

    user_id: str
    group_ids: frozenset[str] = frozenset()
    owned_group_ids: frozenset[str] = frozenset()
    manager: bool = False
    can_add_local: bool = False


@dataclass(frozen=True, slots=True)
class Draft:
    """What an author asks for; cleaned into an :class:`Entry` by the application."""

    slug: str
    level: Level
    display_name: str
    kind: Kind
    owner_group_id: str | None = None
    description: str = ""
    icon: str | None = None
    transport: Transport | None = None
    toolkit_key: str | None = None
    config: dict[str, Any] = field(default_factory=dict[str, Any])
    requires_confirmation_tools: tuple[str, ...] = ()
    instance_ids: tuple[str, ...] = ()


# ---------------------------------------------------------------- names


def check_slug(slug: str) -> str:
    cleaned = slug.strip().lower()
    if not _SLUG.match(cleaned) or cleaned.endswith("-") or "--" in cleaned:
        raise InvalidEntryError(
            "Use a short name of lowercase letters, digits and single hyphens that starts with a letter (linear, "
            "web-search)."
        )
    return cleaned


def slugify(text: str) -> str:
    return _SLUG_CHARS.sub("-", text.lower()).strip("-")[:20].strip("-") or "group"


def registry_name(level: Level, slug: str, *, group_slug: str | None = None, entry_id: str | None = None) -> str:
    """The toolkit name on the runtime: the level comes first, so the same toolkit at two levels never collides."""
    match level:
        case "org":
            name = f"org-{slug}"
        case "team":
            if not group_slug:
                raise InvalidEntryError("A team entry belongs to a group.")
            name = f"team-{group_slug}-{slug}"
        case "custom":
            if not entry_id:
                raise InvalidEntryError("A custom entry needs its id.")
            name = f"custom-{entry_id[-6:].lower()}-{slug}"
    if len(name) > MAX_REGISTRY_NAME:
        raise InvalidEntryError(f"{name!r} is too long; use a shorter name (at most {MAX_REGISTRY_NAME} characters).")
    return name


def default_prefix(name: str) -> str:
    """Prefix for an MCP server's tool names: registry function names are global on a runtime."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] + "_"


# ---------------------------------------------------------------- values


def env_ref(value: object) -> EnvRef | None:
    if not isinstance(value, Mapping) or "env" not in value:
        return None
    data = cast("Mapping[str, Any]", value)
    name = str(data.get("env") or "")
    if not _ENV_NAME.match(name):
        raise InvalidEntryError(f"{name!r} isn't an environment variable name (use UPPER_CASE, digits and _).")
    fmt = data.get("format")
    if fmt is not None and (not isinstance(fmt, str) or fmt.count("{}") != 1):
        raise InvalidEntryError("A format puts the value where {} is, exactly once (Bearer {}).")
    return EnvRef(name, fmt)


def _ref_dict(ref: EnvRef) -> dict[str, Any]:
    return {"env": ref.env} if ref.format is None else {"env": ref.env, "format": ref.format}


def _secret_value(label: str, value: object) -> dict[str, Any]:
    ref = env_ref(value)
    if ref is None:
        raise InvalidEntryError(
            f"{label} is a credential: give the name of an environment variable on the runtime that holds it "
            '({"env": "MY_TOKEN"}), not the value.'
        )
    return _ref_dict(ref)


def clean_tool_names(label: str, value: object) -> tuple[str, ...]:
    """Tool names an author lists (tools to offer, hide, or confirm before running)."""
    return _strings(label, value)


def _strings(label: str, value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in cast("Sequence[Any]", value)):
        raise InvalidEntryError(f"{label} is a list of names.")
    items = tuple(dict.fromkeys(str(item).strip() for item in cast("Sequence[str]", value) if str(item).strip()))
    bad = [item for item in items if not _TOOL_NAME.match(item)]
    if bad:
        raise InvalidEntryError(f"{label}: {', '.join(bad)} aren't tool names.")
    return items


# ---------------------------------------------------------------- MCP servers


def clean_mcp(transport: str | None, config: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    """An MCP server's settings: its transport, where it is, which tools to offer and how to sign in."""
    if transport not in TRANSPORTS:
        raise InvalidEntryError("Pick a transport: streamable-http, sse or stdio.")
    cleaned: dict[str, Any] = {"transport": transport}
    if transport == "stdio":
        command = str(config.get("command") or "").strip()
        if not _COMMAND.match(command):
            raise InvalidEntryError("A stdio server needs a command name (npx, uvx, a binary on the runtime's PATH).")
        args: object = config.get("args") or []
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in cast("list[Any]", args)):
            raise InvalidEntryError("Arguments are a list of strings.")
        env = cast("Mapping[str, Any]", config.get("env") or {})
        cleaned |= {
            "command": command,
            "args": list(cast("list[str]", args)),
            "env": {
                _env_key(key): _secret_value(f"The environment variable {key}", value) for key, value in env.items()
            },
        }
    else:
        cleaned |= {"url": _url(str(config.get("url") or "")), "headers": _headers(config.get("headers") or {})}
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise InvalidEntryError(f"The timeout is a whole number of seconds from 1 to {MAX_TIMEOUT_SECONDS}.")
    prefix = str(config.get("tool_name_prefix") or default_prefix(name))
    if not _PREFIX.match(prefix.rstrip("_")):
        raise InvalidEntryError("A tool name prefix is lowercase letters, digits and _ (linear_).")
    include = _strings("Tools to offer", config.get("include_tools"))
    exclude = _strings("Tools to hide", config.get("exclude_tools"))
    overlap = sorted(set(include) & set(exclude))
    if overlap:
        raise InvalidEntryError(f"{', '.join(overlap)} can't be both offered and hidden.")
    return cleaned | {
        "timeout_seconds": timeout,
        "tool_name_prefix": prefix,
        "include_tools": list(include),
        "exclude_tools": list(exclude),
    }


def _env_key(key: str) -> str:
    if not _ENV_NAME.match(key):
        raise InvalidEntryError(f"{key!r} isn't an environment variable name.")
    return key


def _url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidEntryError("The server URL is an http(s) URL (https://mcp.example.com/mcp).")
    if parts.username or parts.password:
        raise InvalidEntryError("Don't put credentials in the URL; send them in a header from an environment variable.")
    secret = [key for key, _ in parse_qsl(parts.query) if _CREDENTIAL.search(key)]
    if secret:
        raise InvalidEntryError(
            f"The URL carries {', '.join(secret)}; send credentials in a header from an environment variable instead."
        )
    return url


def _headers(headers: object) -> dict[str, Any]:
    if not isinstance(headers, Mapping):
        raise InvalidEntryError("Headers map names to values.")
    cleaned: dict[str, Any] = {}
    for raw_name, value in cast("Mapping[str, Any]", headers).items():
        name = str(raw_name).strip()
        if not re.match(r"^[A-Za-z0-9-]{1,100}$", name):
            raise InvalidEntryError(f"{name!r} isn't a header name.")
        ref = env_ref(value)
        if ref is not None:
            cleaned[name] = _ref_dict(ref)
        elif _CREDENTIAL.search(name):
            cleaned[name] = _secret_value(f"The header {name}", value)
        elif isinstance(value, str) and len(value) <= 500:  # noqa: PLR2004
            cleaned[name] = value
        else:
            raise InvalidEntryError(f"The header {name} is a short text or an environment variable.")
    return cleaned


# ---------------------------------------------------------------- Agno toolkits


def clean_toolkit(toolkit: ToolkitInfo | None, config: Mapping[str, Any]) -> dict[str, Any]:
    """A toolkit's constructor parameters, checked against the shared list (credentials only as env refs)."""
    if toolkit is None:
        raise InvalidEntryError("Pick a toolkit from the list.")
    params = cast("Mapping[str, Any]", config.get("params") or {})
    cleaned: dict[str, Any] = {}
    for name, value in params.items():
        spec = toolkit.param(name)
        if spec is None:
            raise InvalidEntryError(f"{toolkit.label} has no parameter {name!r}.")
        if value is None:
            continue
        ref = env_ref(value)
        if spec.secret:
            cleaned[name] = _secret_value(f"{toolkit.label}'s {name}", value)
        elif ref is not None:
            cleaned[name] = _ref_dict(ref)
        else:
            cleaned[name] = _typed(toolkit.label, spec, value)
    missing = [spec.name for spec in toolkit.params if spec.required and spec.name not in cleaned]
    if missing:
        raise InvalidEntryError(f"{toolkit.label} needs {', '.join(missing)}.")
    return {"params": cleaned}


def _typed(label: str, spec: ToolkitParamInfo, value: object) -> object:
    ok: bool
    match spec.type:
        case "str":
            ok = isinstance(value, str)
        case "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
        case "float":
            ok = isinstance(value, int | float) and not isinstance(value, bool)
        case "bool":
            ok = isinstance(value, bool)
        case "list":
            ok = isinstance(value, list)
        case "dict":
            ok = isinstance(value, dict)
        case "choice":
            ok = value in spec.choices
        case _:
            ok = isinstance(value, str | int | float | bool | list | dict)
    if not ok:
        expected = f"one of {', '.join(map(repr, spec.choices))}" if spec.type == "choice" else f"a {spec.type}"
        raise InvalidEntryError(f"{label}'s {spec.name} is {expected}.")
    return value


# ---------------------------------------------------------------- who sees and changes what


def visible(entry: Entry, viewer: Viewer) -> bool:
    if viewer.manager:
        return True
    match entry.level:
        case "org":
            return entry.status == "active"
        case "team":
            return entry.owner_group_id in viewer.group_ids
        case "custom":
            return entry.created_by == viewer.user_id or (
                entry.owner_group_id is not None and entry.owner_group_id in viewer.group_ids
            )


def may_change(entry_level: Level, owner_group_id: str | None, created_by: str | None, viewer: Viewer) -> bool:
    """Org: catalog managers. Team: the group's owners. Custom: its author. Managers may change any entry."""
    if viewer.manager:
        return True
    match entry_level:
        case "org":
            return False
        case "team":
            return owner_group_id is not None and owner_group_id in viewer.owned_group_ids
        case "custom":
            return created_by == viewer.user_id


def same_tool(entry: Entry, others: Sequence[Entry]) -> list[Entry]:
    """Other entries offering the same toolkit or server: the "an organization version exists" hint."""
    return [other for other in others if other.id != entry.id and other.same_as_key == entry.same_as_key]


def order_key(entry: Entry) -> tuple[int, str]:
    return LEVELS.index(entry.level), entry.display_name.lower()
