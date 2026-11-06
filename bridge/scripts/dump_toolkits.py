"""Write the list of Agno toolkits the tool catalog offers, read from the installed agno's sources.

The sources are parsed, never imported: most toolkits need an optional package (``ddgs``, ``PyGithub``, ...) that
the machine running this script may not have. For each ``Toolkit`` subclass under ``agno.tools`` the script records
its import path, its constructor parameters (type, default, whether it is required, the docstring's description) and
the package its ImportError tells people to install.

Usage (from ``bridge/``)::

    uv run python scripts/dump_toolkits.py          # rewrite both copies
    uv run python scripts/dump_toolkits.py --check  # fail when either copy is stale

It writes ``src/agnostic_bridge/toolkits.json`` (what the bridge builds from) and the control plane's copy in
``backend/packages/agnostic-spec/src/agnostic_spec/toolkits.json`` (what its forms and checks read).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import agno

BRIDGE = Path(__file__).resolve().parents[1]
TARGETS = (
    BRIDGE / "src" / "agnostic_bridge" / "toolkits.json",
    BRIDGE.parent / "backend" / "packages" / "agnostic-spec" / "src" / "agnostic_spec" / "toolkits.json",
)
FORMAT_VERSION = 1

# Toolkits that need the running agent, team, OS or database to work: they can't be built from a catalog entry.
FRAMEWORK = frozenset(
    {
        "advisor",
        "agentos",
        "company",
        "component",
        "decorator",
        "function",
        "knowledge",
        "mcp",
        "mcp_toolbox",
        "memory",
        "models",
        "reasoning",
        "scheduler",
        "studio",
        "studio_runner",
        "studio_schema",
        "tool_registry",
        "toolkit",
        "user_control_flow",
        "user_feedback",
        "workflow",
        "workspace",
        "xai_auth",
    }
)

# Helpers that subclass Toolkit but aren't tools people add.
EXCLUDED_CLASSES = frozenset({"GoogleAuth", "GoogleToolkit", "XAIAuth"})

# Brand spellings the class names lose when split into words.
LABELS = {
    "AgentQLTools": "AgentQL",
    "AWSLambdaTools": "AWS Lambda",
    "AWSSESTool": "AWS SES",
    "CalComTools": "Cal.com",
    "ClickUpTools": "ClickUp",
    "DalleTools": "DALL-E",
    "DuckDbTools": "DuckDB",
    "DuckDuckGoTools": "DuckDuckGo",
    "E2BTools": "E2B",
    "GithubTools": "GitHub",
    "GitlabTools": "GitLab",
    "HackerNewsTools": "Hacker News",
    "LinkupTools": "Linkup",
    "MLXTranscribeTools": "MLX Transcribe",
    "OpenAITools": "OpenAI",
    "OpenBBTools": "OpenBB",
    "OpenCVTools": "OpenCV",
    "SQLTools": "SQL",
    "SixtyDBTools": "SixtyDB",
    "WhatsAppTools": "WhatsApp",
    "XTools": "X",
    "YFinanceTools": "Yahoo Finance",
    "YouTubeTools": "YouTube",
}

# Toolkits that run commands or touch the runtime's own files: only owners and administrators may add them, and a
# runtime builds them only after opting in (the same rule as stdio MCP servers).
LOCAL = frozenset({"code", "coding", "docker", "file", "file_generation", "local_file_system", "python", "shell"})

CATEGORIES: dict[str, tuple[str, ...]] = {
    "search": (
        "baidusearch",
        "bravesearch",
        "duckduckgo",
        "exa",
        "keenable",
        "linkup",
        "parallel",
        "perplexity",
        "scavio",
        "searchapi",
        "searxng",
        "seltz",
        "serpapi",
        "serper",
        "serply",
        "tavily",
        "valyu",
        "websearch",
        "youcom",
        "arxiv",
        "pubmed",
        "wikipedia",
        "hackernews",
    ),
    "web": (
        "agentql",
        "anakin",
        "apify",
        "brightdata",
        "browserbase",
        "crawl4ai",
        "firecrawl",
        "jina",
        "llms_txt",
        "newspaper",
        "newspaper4k",
        "oxylabs",
        "scrapegraph",
        "spider",
        "trafilatura",
        "webbrowser",
        "website",
        "webtools",
        "brandfetch",
    ),
    "social": (
        "discord",
        "email",
        "atomic_mail",
        "aws_ses",
        "plivo",
        "reddit",
        "resend",
        "slack",
        "telegram",
        "twilio",
        "webex",
        "whatsapp",
        "x",
        "zoom",
    ),
    "data": (
        "csv_toolkit",
        "duckdb",
        "neo4j",
        "pandas",
        "postgres",
        "redshift",
        "sql",
        "sixtydb",
        "financial_datasets",
        "openbb",
        "yfinance",
        "adanos",
        "evm",
    ),
    "productivity": (
        "airflow",
        "bitbucket",
        "calcom",
        "clickup",
        "confluence",
        "github",
        "gitlab",
        "jira",
        "linear",
        "notion",
        "redmine",
        "salesforce",
        "shopify",
        "todoist",
        "trello",
        "zendesk",
        "google",
    ),
    "media": (
        "cartesia",
        "dalle",
        "desi_vocal",
        "eleven_labs",
        "fal",
        "giphy",
        "lumalab",
        "minimax",
        "mlx_transcribe",
        "models_labs",
        "moviepy_video",
        "nano_banana",
        "opencv",
        "replicate",
        "smallest",
        "spotify",
        "twelvelabs",
        "unsplash",
        "wavespeed",
        "youtube",
    ),
    "local": tuple(sorted(LOCAL)),
}

SECRET = re.compile(r"(api_?key|token|secret|password|passwd|credential|private_key|auth)", re.IGNORECASE)
INSTALL = re.compile(r"pip install ([^`'\"\n]+)")
DOC_ARG = re.compile(r"^\s{4,}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$")


@dataclass
class Param:
    name: str
    type: str
    required: bool
    default: Any = None
    choices: list[Any] = field(default_factory=list)
    secret: bool = False
    description: str = ""


@dataclass
class ClassInfo:
    module: str
    name: str
    bases: list[str]
    node: ast.ClassDef
    source: str


def _annotation(node: ast.expr | None) -> tuple[str, list[Any]]:
    """A form type for an annotation: str, int, float, bool, list, dict, choice or json."""
    if node is None:
        return "str", []
    text = ast.unparse(node)
    inner = text
    for wrapper in ("Optional[", "Union["):
        if inner.startswith(wrapper):
            inner = inner[len(wrapper) : -1]
    inner = re.sub(r",\s*None\b|\bNone\s*,\s*|\s*\|\s*None\b|\bNone\s*\|\s*", "", inner).strip()
    if inner.startswith("Literal["):
        try:
            literal = ast.parse(inner, mode="eval").body
            assert isinstance(literal, ast.Subscript)
            values = literal.slice.elts if isinstance(literal.slice, ast.Tuple) else [literal.slice]
            return "choice", [ast.literal_eval(value) for value in values]
        except (SyntaxError, ValueError, AssertionError):
            return "str", []
    base = inner.split("[", 1)[0].lower()
    mapping = {"str": "str", "int": "int", "float": "float", "bool": "bool", "list": "list", "dict": "dict"}
    return mapping.get(base, "json"), []


def _default(node: ast.expr | None) -> tuple[bool, Any]:
    if node is None:
        return False, None
    try:
        return True, ast.literal_eval(node)
    except ValueError:
        return True, None  # a computed default (os.getenv(...)): optional, nothing to show


def _descriptions(doc: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in doc.splitlines():
        match = DOC_ARG.match(line)
        if match and match.group(1) not in found:
            found[match.group(1)] = match.group(2).strip()
    return found


def _params(init: ast.FunctionDef, doc: str) -> list[Param]:
    args = init.args
    positional = [*args.posonlyargs, *args.args][1:]  # drop self
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs = [*zip(positional, defaults, strict=True), *zip(args.kwonlyargs, args.kw_defaults, strict=True)]
    descriptions = _descriptions(doc)
    params: list[Param] = []
    for arg, default_node in pairs:
        kind, choices = _annotation(arg.annotation)
        has_default, default = _default(default_node)
        if not isinstance(default, str | int | float | bool | list | dict | type(None)):
            default = None
        params.append(
            Param(
                name=arg.arg,
                type=kind,
                required=not has_default,
                default=default,
                choices=choices,
                secret=bool(SECRET.search(arg.arg)) and kind in {"str", "json"},
                description=descriptions.get(arg.arg, ""),
            )
        )
    return params


def _words(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).strip()


def _key(name: str) -> str:
    stem = re.sub(r"(Tools?|Toolkit)$", "", name) or name
    return re.sub(r"[^a-z0-9]+", "_", _words(stem).lower()).strip("_")


def _label(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    stem = name.removesuffix("Tools").removesuffix("Toolkit") or name
    return _words(stem)


def _category(module_key: str) -> str:
    for category, keys in CATEGORIES.items():
        if module_key in keys:
            return category
    return "other"


def _collect(root: Path) -> list[ClassInfo]:
    classes: list[ClassInfo] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root.parent.parent).with_suffix("")
        module = ".".join(relative.parts).removesuffix(".__init__")
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(base).rsplit(".", 1)[-1] for base in node.bases]
                classes.append(ClassInfo(module=module, name=node.name, bases=bases, node=node, source=source))
    return classes


def _is_toolkit(info: ClassInfo, by_name: dict[str, ClassInfo], seen: frozenset[str] = frozenset()) -> bool:
    for base in info.bases:
        if base == "Toolkit":
            return True
        parent = by_name.get(base)
        if parent is not None and base not in seen and _is_toolkit(parent, by_name, seen | {info.name}):
            return True
    return False


def _init(info: ClassInfo, by_name: dict[str, ClassInfo]) -> ast.FunctionDef | None:
    for item in info.node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            return item
    for base in info.bases:
        parent = by_name.get(base)
        if parent is not None and parent.name != info.name:
            return _init(parent, by_name)
    return None


def build() -> dict[str, Any]:
    tools_dir = Path(agno.__file__).resolve().parent / "tools"
    classes = _collect(tools_dir)
    by_name = {info.name: info for info in classes}
    toolkits: list[dict[str, Any]] = []
    for info in classes:
        if (
            info.name.startswith("_")
            or info.name in EXCLUDED_CLASSES
            or info.name == "Toolkit"
            or not _is_toolkit(info, by_name)
        ):
            continue
        module_key = info.module.removeprefix("agno.tools.").split(".", 1)[0]
        if module_key in FRAMEWORK:
            continue
        init = _init(info, by_name)
        doc = ast.get_docstring(info.node) or ""
        init_doc = (ast.get_docstring(init) or "") if init else ""
        params = [p for p in (_params(init, f"{doc}\n{init_doc}") if init else []) if not p.name.startswith("_")]
        install = INSTALL.search(info.source)
        summary = next((line.strip() for line in doc.splitlines() if line.strip()), "")
        toolkits.append(
            {
                "key": _key(info.name),
                "class_path": f"{info.module}:{info.name}",
                "label": _label(info.name),
                "description": summary,
                "category": _category(module_key),
                "local": module_key in LOCAL,
                "extra": install.group(1).strip().rstrip(".") if install else None,
                "params": [vars(param) for param in params],
            }
        )
    unique: dict[str, dict[str, Any]] = {}
    for toolkit in sorted(toolkits, key=lambda item: item["class_path"]):
        unique.setdefault(toolkit["key"], toolkit)
    return {
        "version": FORMAT_VERSION,
        "agno_version": agno.__version__,
        "toolkits": sorted(unique.values(), key=lambda t: t["key"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail when a written copy differs")
    options = parser.parse_args()
    text = json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    stale = [target for target in TARGETS if not target.exists() or target.read_text(encoding="utf-8") != text]
    if options.check:
        for target in stale:
            print(f"stale: {target}", file=sys.stderr)
        return 1 if stale else 0
    for target in stale:
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
