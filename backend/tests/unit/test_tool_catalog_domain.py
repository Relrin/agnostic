"""Tool catalog rules: names per level, credentials only as env refs, who sees and changes what, the manifest."""

from datetime import UTC, datetime
from typing import Any

import pytest

from agnostic_spec.toolkits import toolkit_list
from agnostic_tool_catalog.application.toolkits import Toolkits
from agnostic_tool_catalog.domain.entries import (
    Entry,
    InvalidEntryError,
    Viewer,
    check_slug,
    clean_mcp,
    clean_toolkit,
    may_change,
    registry_name,
    same_tool,
    visible,
)
from agnostic_tool_catalog.domain.manifest import build_manifest, etag

NOW = datetime(2026, 11, 6, tzinfo=UTC)


def entry(**overrides: Any) -> Entry:
    values: dict[str, Any] = {
        "id": "tce_01TEST000000000000000ABCDEF",
        "slug": "search",
        "registry_name": "org-search",
        "level": "org",
        "owner_group_id": None,
        "display_name": "Search",
        "description": "",
        "icon": None,
        "kind": "toolkit",
        "transport": None,
        "toolkit_key": "duck_duck_go",
        "config": {"params": {}},
        "requires_confirmation_tools": (),
        "instance_ids": (),
        "status": "active",
        "version": 1,
        "created_by": "usr_author",
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Entry(**(values | overrides))


def test_registry_names_put_the_level_first() -> None:
    assert registry_name("org", "linear") == "org-linear"
    assert registry_name("team", "linear", group_slug="data") == "team-data-linear"
    assert registry_name("custom", "linear", entry_id="tce_01ABCDEFGHJKMNPQRS7K2P9Q") == "custom-7k2p9q-linear"
    with pytest.raises(InvalidEntryError):
        registry_name("team", "linear")


@pytest.mark.parametrize("slug", ["Linear!", "-x", "x-", "a--b", "1abc", "a" * 41])
def test_slugs_are_short_lowercase_names(slug: str) -> None:
    with pytest.raises(InvalidEntryError):
        check_slug(slug)


def test_mcp_credentials_must_be_env_refs() -> None:
    cleaned = clean_mcp(
        "streamable-http",
        {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": {"env": "TOKEN"}, "X-Team": "data"}},
        name="org-linear",
    )
    assert cleaned["headers"] == {"Authorization": {"env": "TOKEN"}, "X-Team": "data"}
    assert cleaned["tool_name_prefix"] == "org_linear_"
    for headers in ({"Authorization": "Bearer x"}, {"X-Api-Key": "k"}, {"Cookie": "s=1"}):
        with pytest.raises(InvalidEntryError, match="environment variable"):
            clean_mcp("sse", {"url": "https://mcp.example.com/sse", "headers": headers}, name="org-x")
    with pytest.raises(InvalidEntryError):
        clean_mcp("sse", {"url": "https://u:p@mcp.example.com/sse"}, name="org-x")
    with pytest.raises(InvalidEntryError):
        clean_mcp("sse", {"url": "https://mcp.example.com/sse?token=x"}, name="org-x")
    with pytest.raises(InvalidEntryError):
        clean_mcp("stdio", {"command": "npx", "env": {"TOKEN": "literal"}}, name="org-x")


def test_stdio_needs_a_bare_command() -> None:
    cleaned = clean_mcp("stdio", {"command": "npx", "args": ["-y", "server"]}, name="org-fs")
    assert cleaned["command"] == "npx"
    with pytest.raises(InvalidEntryError):
        clean_mcp("stdio", {"command": "sh -c 'rm -rf /'"}, name="org-fs")


def test_toolkit_parameters_follow_the_list() -> None:
    toolkits = Toolkits(toolkit_list())
    github = toolkits.info("github")
    assert clean_toolkit(github, {"params": {"access_token": {"env": "GH"}}}) == {
        "params": {"access_token": {"env": "GH"}}
    }
    with pytest.raises(InvalidEntryError, match="environment variable"):
        clean_toolkit(github, {"params": {"access_token": "ghp_x"}})
    with pytest.raises(InvalidEntryError, match="no parameter"):
        clean_toolkit(github, {"params": {"exec": "x"}})
    with pytest.raises(InvalidEntryError):
        clean_toolkit(toolkits.info("duck_duck_go"), {"params": {"enable_search": "yes"}})
    with pytest.raises(InvalidEntryError):
        clean_toolkit(None, {})


def test_who_sees_and_changes_each_level() -> None:
    team = entry(level="team", owner_group_id="grp_data", registry_name="team-data-search")
    custom = entry(level="custom", owner_group_id=None, registry_name="custom-abcdef-search")
    member = Viewer(user_id="usr_member", group_ids=frozenset({"grp_data"}))
    group_owner = Viewer(
        user_id="usr_owner", group_ids=frozenset({"grp_data"}), owned_group_ids=frozenset({"grp_data"})
    )
    outsider = Viewer(user_id="usr_other")
    admin = Viewer(user_id="usr_admin", manager=True)

    assert visible(entry(), outsider)
    assert not visible(entry(status="disabled"), outsider)
    assert visible(team, member)
    assert not visible(team, outsider)
    assert visible(team, admin)
    assert visible(custom, Viewer(user_id="usr_author"))
    assert not visible(custom, member)

    assert not may_change("org", None, None, group_owner)
    assert may_change("org", None, None, admin)
    assert may_change("team", "grp_data", None, group_owner)
    assert not may_change("team", "grp_data", None, member)
    assert may_change("custom", None, "usr_author", Viewer(user_id="usr_author"))


def test_the_same_toolkit_at_two_levels_is_pointed_out() -> None:
    org = entry()
    team = entry(id="tce_2", level="team", owner_group_id="grp", registry_name="team-data-search")
    other = entry(id="tce_3", toolkit_key="wikipedia", registry_name="org-wiki")
    assert same_tool(team, [org, team, other]) == [org]


def test_the_manifest_holds_active_entries_for_the_instance() -> None:
    entries = [
        entry(),
        entry(id="tce_2", registry_name="org-off", status="disabled"),
        entry(id="tce_3", registry_name="org-elsewhere", instance_ids=("ins_other",)),
        entry(id="tce_4", registry_name="org-here", instance_ids=("ins_here",)),
    ]
    manifest = build_manifest("ins_here", entries)
    assert [item["name"] for item in manifest["entries"]] == ["org-here", "org-search"]
    assert manifest["entries"][0]["toolkit"] == "duck_duck_go"
    assert etag(manifest) == etag(build_manifest("ins_here", list(reversed(entries))))
    changed = build_manifest("ins_here", [entry(display_name="Other"), *entries[1:]])
    assert etag(changed) != etag(manifest)
