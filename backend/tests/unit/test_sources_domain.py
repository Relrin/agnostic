"""Code source rules: path mappings, outcome sentences, templates, webhook signatures and secret redaction."""

import pytest

from agnostic_sources.domain.model import PathMapping, SourceRuleError
from agnostic_sources.domain.outcomes import Outcome, codeowners, review_sentence, sentence, team_label
from agnostic_sources.domain.paths import (
    DEFAULT_MAPPINGS,
    check_path,
    component_target,
    counts,
    folder_of,
    match,
    pathspecs,
)
from agnostic_sources.domain.remote import check_clone_url, check_repo, redact, ssh_address
from agnostic_sources.domain.templates import (
    DEFAULT_BRANCH_TEMPLATE,
    branch_name,
    check_template,
    commit_message,
    render,
    unique_branch,
)
from agnostic_sources.domain.webhooks import hmac_sha256, pull_event, push_event, verify


def test_default_mappings() -> None:
    assert match(DEFAULT_MAPPINGS, "agents/support_triage.py") == DEFAULT_MAPPINGS[0]
    assert match(DEFAULT_MAPPINGS, "agents/nested/x.py") is None
    assert match(DEFAULT_MAPPINGS, "registry.py") == DEFAULT_MAPPINGS[3]
    assert match(DEFAULT_MAPPINGS, "tests/test_agents.py") == DEFAULT_MAPPINGS[4]
    assert component_target(DEFAULT_MAPPINGS, "registry.py") is None
    assert component_target(DEFAULT_MAPPINGS, "workflows/ticket_router.py") == DEFAULT_MAPPINGS[2]
    assert not DEFAULT_MAPPINGS[3].effective_writable
    paths = ["agents/a.py", "agents/b.py", "teams/t.py", "registry.py", "utils/x.py", "README.md"]
    assert counts(DEFAULT_MAPPINGS, paths) == [2, 1, 0, 1, 1]
    assert pathspecs(DEFAULT_MAPPINGS) == [
        ":(glob)agents/*.py",
        ":(glob)teams/*.py",
        ":(glob)workflows/*.py",
        ":(glob)registry.py",
    ]
    assert folder_of("agents/*.py") == "agents"
    assert folder_of("src/**/agents/*.py") == "src"


def test_ignored_wins_and_globs_cross_folders_only_with_double_star() -> None:
    mappings = (PathMapping("**/agents/*.py", "agents"), PathMapping("legacy/", "ignored"))
    assert match(mappings, "pkg/agents/a.py") == mappings[0]
    assert match(mappings, "agents/a.py") == mappings[0]
    assert match(mappings, "legacy/agents/a.py") == mappings[1]


@pytest.mark.parametrize("path", ["../x.py", "/etc/passwd", "a\\b.py", "a/./b.py", "C:/x.py", ""])
def test_paths_outside_the_repository_are_refused(path: str) -> None:
    with pytest.raises(SourceRuleError):
        _ = check_path(path)


def test_outcome_sentences_depend_on_the_reader() -> None:
    outcome = Outcome(
        "new_draft",
        "ticket-router",
        "workflow",
        9,
        beside_version=8,
        beside_author_id="usr_me",
        beside_author_name="Maya Chen",
    )
    assert sentence(outcome, "usr_me") == "Becomes draft v9 of ticket-router, next to your draft v8"
    assert sentence(outcome, "usr_other") == "Becomes draft v9 of ticket-router, next to Maya Chen's draft v8"
    assert sentence(Outcome("new_draft", "kb-researcher", "agent", 9)) == "Becomes draft v9 of kb-researcher"
    assert sentence(Outcome("new_component", "triage", "agent")) == "Creates triage as a new agent (draft v1)"
    conflict = Outcome(
        "conflict",
        "billing-agent",
        "agent",
        beside_version=6,
        beside_author_id="usr_me",
        conflict_paths=["instructions[2]"],
    )
    assert sentence(conflict, "usr_me") == "Conflicts with your draft v6 on instructions[2]"
    assert sentence(Outcome("unparseable", problems=2)) == "Can't become a draft: 2 problems in the code"
    assert Outcome.of(outcome.as_dict()) == outcome


def test_review_requirements() -> None:
    assert review_sentence(1, ["Platform"]) == "1 review from Platform required"
    assert review_sentence(0, []) == "No review required"
    assert team_label("@northwind/platform") == "Platform"
    owners = "* @northwind/everyone\n/agents/ @northwind/platform\n"
    assert codeowners(owners, "agents/support_triage.py") == ["@northwind/platform"]
    assert codeowners(owners, "workflows/x.py") == ["@northwind/everyone"]


def test_templates() -> None:
    values = {"component": "support-triage", "version": 4, "summary": "lower temperature, add refund rule"}
    assert branch_name(render(DEFAULT_BRANCH_TEMPLATE, values)) == "studio/support-triage-v4"
    assert branch_name("studio/../a b~c") == "studio/a-b-c"
    assert unique_branch("studio/x-v4", ["studio/x-v4", "studio/x-v4-2"]) == "studio/x-v4-3"
    assert commit_message("{component}: {summary}", values) == "support-triage: lower temperature, add refund rule\n"
    with pytest.raises(SourceRuleError):
        _ = check_template("{componnent}-v{version}", branch=True)


def test_webhook_signatures() -> None:
    body = b'{"ref":"refs/heads/main"}'
    signature = hmac_sha256("s3cret", body)
    assert verify("github", "s3cret", body, {"x-hub-signature-256": f"sha256={signature}"})
    assert not verify("github", "s3cret", body, {"x-hub-signature-256": signature})
    assert not verify("github", "", body, {"x-hub-signature-256": f"sha256={hmac_sha256('', body)}"})
    assert verify("gitea", "s3cret", body, {"x-gitea-signature": signature})
    assert verify("forgejo", "s3cret", body, {"x-forgejo-signature": signature})
    assert not verify("gitea", "other", body, {"x-gitea-signature": signature})
    assert verify("gitlab", "s3cret", body, {"x-gitlab-token": "s3cret"})
    assert not verify("gitlab", "s3cret", body, {"x-gitlab-token": "nope"})


def test_webhook_payloads() -> None:
    push = push_event(
        "gitea",
        {
            "ref": "refs/heads/main",
            "before": "a" * 40,
            "after": "b" * 40,
            "repository": {"full_name": "northwind/x"},
            "pusher": {"login": "sam"},
        },
    )
    assert push is not None
    assert (push.repo, push.branch, push.after, push.pusher) == ("northwind/x", "main", "b" * 40, "sam")
    merged = pull_event(
        "github",
        {
            "action": "closed",
            "number": 12,
            "pull_request": {"merged": True, "merge_commit_sha": "c" * 40},
            "repository": {"full_name": "northwind/x"},
        },
    )
    assert merged is not None
    assert (merged.number, merged.merged, merged.merge_sha) == (12, True, "c" * 40)
    gitlab = pull_event(
        "gitlab",
        {
            "object_kind": "merge_request",
            "project": {"path_with_namespace": "northwind/data"},
            "object_attributes": {"iid": 3, "action": "merge", "state": "merged"},
        },
    )
    assert gitlab is not None
    assert (gitlab.repo, gitlab.number, gitlab.merged) == ("northwind/data", 3, True)


def test_remote_rules() -> None:
    assert check_repo("northwind/agent-platform.git") == "northwind/agent-platform"
    with pytest.raises(SourceRuleError):
        _ = check_repo("../etc")
    with pytest.raises(SourceRuleError):
        _ = check_clone_url("https://user:token@github.com/x/y.git")
    with pytest.raises(SourceRuleError):
        _ = check_clone_url("file:///tmp/repo")
    assert check_clone_url("file:///tmp/repo", allow_file=True)
    scp = "git@git.northwind.test:northwind/agents.git"
    assert check_clone_url(scp) == scp
    with pytest.raises(SourceRuleError):
        _ = check_clone_url("git@git.northwind.test:-oProxyCommand=x")
    assert ssh_address("ssh://git@git.northwind.test:2222/") == "ssh://git@git.northwind.test:2222"
    for wrong in ("https://git.northwind.test", "ssh://git@host:22x", "ssh://git@host:2222/owner/repo.git"):
        with pytest.raises(SourceRuleError):
            _ = ssh_address(wrong)
    text = "fatal: https://x-access-token:ghs_abcdefghijklmnopqrstuvwxyz@github.com Authorization: Basic Zm9vOmJhcg=="
    assert "ghs_" not in redact(text)
    assert "Zm9v" not in redact(text)
