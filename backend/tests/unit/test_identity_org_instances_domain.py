"""Kernel additions (ephemeral store, envelope encryption, settings) and the pure rules of identity, org,
instances and audit."""

import base64
from datetime import UTC, datetime

import pytest

from agnostic_audit.domain.events import ANONYMOUS, AuditEntry, partition_expired, partitions_to_create, render_summary
from agnostic_audit.infrastructure.repository import upper_bound
from agnostic_identity.domain.providers import Preset, ProviderConfigError, resolve_provider
from agnostic_identity.domain.users import (
    InvalidEmailError,
    WeakPasswordError,
    check_password,
    normalize_email,
    safe_next,
)
from agnostic_identity.settings import IdentitySettings
from agnostic_instances.domain.instances import (
    InstanceRuleError,
    check_slug,
    clean_endpoint,
    config_snippet,
    minor,
    slug_from,
    version_supported,
)
from agnostic_kernel.crypto import SecretBox, SecretDecryptionError, SecretsConfigError, load_master_key
from agnostic_kernel.ephemeral import MemoryStore, access_generation, bump_access_generation
from agnostic_kernel.settings import SecretsSettings
from agnostic_kernel.testing import make_settings
from agnostic_org.domain.org import OrgRole, OrgRuleError, check_invite_role, check_removal, check_role_change, slugify


async def test_memory_store_ttl_incr_and_pop() -> None:
    clock = [0.0]
    store = MemoryStore(clock=lambda: clock[0])
    await store.set("a", b"1", ttl=10)
    assert await store.get("a") == b"1"
    assert not await store.set_if_absent("a", b"2", ttl=5)
    assert await store.incr("n", ttl=5) == 1
    assert await store.incr("n", ttl=5) == 2
    assert await store.pop("a") == b"1"
    assert await store.get("a") is None
    clock[0] = 6
    assert await store.get("n") is None
    assert await access_generation(store) == "0"
    await bump_access_generation(store)
    assert await access_generation(store) == "1"


def test_secret_box() -> None:
    key = bytes(range(32))
    box = SecretBox(key)
    sealed = box.seal(b"private key")
    assert sealed.startswith(f"v1.{box.key_id}.")
    assert box.open(sealed) == b"private key"
    assert box.seal(b"private key") != sealed  # fresh data key and nonce each time
    with pytest.raises(SecretDecryptionError):
        SecretBox(bytes(32)).open(sealed)
    tampered = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
    with pytest.raises(SecretDecryptionError):
        box.open(tampered)


def test_master_key_loading() -> None:
    encoded = base64.b64encode(bytes(range(32))).decode()
    assert load_master_key(SecretsSettings(master_key=encoded), environment="production") == bytes(range(32))  # pyright: ignore[reportArgumentType]
    with pytest.raises(SecretsConfigError):
        load_master_key(SecretsSettings(), environment="production")
    with pytest.raises(SecretsConfigError):
        load_master_key(SecretsSettings(master_key="c2hvcnQ="), environment="development")  # pyright: ignore[reportArgumentType]
    assert len(load_master_key(SecretsSettings(), environment="development")) == 32


def test_settings_derivations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGNOSTIC_HTTP__PUBLIC_URL", raising=False)  # a developer's .env may set it
    sqlite = make_settings("sqlite:///x.db")
    assert sqlite.cache_backend() == "memory"
    assert make_settings("postgresql://h/db").cache_backend() == "redis"
    assert sqlite.public_url() == "http://127.0.0.1:8000"
    assert not sqlite.secure_cookies()
    public = make_settings("sqlite:///x.db", http={"public_url": "https://agnostic.localhost.company/"})
    assert public.public_url() == "https://agnostic.localhost.company"
    assert public.secure_cookies()
    redacted = make_settings("sqlite:///x.db", smtp={"url": "smtp://u:pw@mail:587"}).redacted()
    assert redacted["smtp"]["url"] == "smtp://u:***@mail:587"


def test_emails_passwords_and_redirects() -> None:
    assert normalize_email("  Marcus@Localhost.COMPANY ") == "marcus@localhost.company"
    with pytest.raises(InvalidEmailError):
        normalize_email("marcus")
    check_password("correct horse battery staple", email="daniel@localhost.company", min_length=12)
    with pytest.raises(WeakPasswordError):
        check_password("short", email="daniel@localhost.company", min_length=12)
    with pytest.raises(WeakPasswordError):
        check_password("daniel@localhost.company", email="daniel@localhost.company", min_length=12)
    assert safe_next("/access/people") == "/access/people"
    for evil in ("https://evil.example", "//evil.example", "/\\evil", None, ""):
        assert safe_next(evil) == "/"


def test_provider_presets() -> None:
    google = resolve_provider(
        "google", preset=Preset.GOOGLE, client_id="c", client_secret="s", allowed_email_domains=["@Localhost.company"]
    )
    assert google.issuer == "https://accounts.google.com"
    assert google.extra_authorize_params["hd"] == "localhost.company"
    assert not google.jit_allows("marcus@localhost.company")  # JIT off by default
    gitlab = resolve_provider("gitlab", preset=Preset.GITLAB, client_id="c", client_secret=None)
    assert gitlab.issuer == "https://gitlab.com"
    assert gitlab.base_url is None
    # Self-managed GitLab: the admin form's "GitLab URL" (base_url) is the issuer.
    hosted = resolve_provider(
        "gitlab", preset=Preset.GITLAB, client_id="c", client_secret=None, base_url="https://gitlab.corp/"
    )
    assert (hosted.issuer, hosted.base_url) == ("https://gitlab.corp", "https://gitlab.corp")
    # A row stored with the gitlab.com default issuer next to a self-managed URL signs in at the self-managed one.
    stored = resolve_provider(
        "gitlab",
        preset=Preset.GITLAB,
        client_id="c",
        client_secret=None,
        issuer="https://gitlab.com",
        base_url="https://gitlab.corp",
    )
    assert stored.issuer == "https://gitlab.corp"
    # An issuer alone (env settings from before the GitLab URL existed) still points at the instance.
    issuer_only = resolve_provider(
        "gitlab", preset=Preset.GITLAB, client_id="c", client_secret=None, issuer="https://example.com/gitlab/"
    )
    assert (issuer_only.issuer, issuer_only.base_url) == ("https://example.com/gitlab", "https://example.com/gitlab")
    okta = resolve_provider(
        "okta",
        preset=Preset.OKTA,
        client_id="c",
        client_secret="s",
        issuer="https://localhost-company.okta.com/oauth2/default/",
        jit_provisioning=True,
        allowed_email_domains=["localhost.company"],
    )
    assert okta.issuer == "https://localhost-company.okta.com/oauth2/default"
    assert okta.jit_allows("marcus@localhost.company")
    assert not okta.jit_allows("evan@elsewhere.dev")
    with pytest.raises(ProviderConfigError):
        resolve_provider("okta", preset=Preset.OKTA, client_id="c", client_secret="s")
    ghe = resolve_provider("ghe", preset=Preset.GITHUB, client_id="c", client_secret="s", base_url="https://git.corp/")
    assert ghe.base_url == "https://git.corp"


def test_identity_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__PRESET", "gitlab")
    monkeypatch.setenv("AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__CLIENT_ID", "abc")
    monkeypatch.setenv("AGNOSTIC_IDENTITY__PROVIDERS__GITLAB__ALLOWED_EMAIL_DOMAINS", "localhost.company, acme.dev")
    monkeypatch.setenv("AGNOSTIC_IDENTITY__LOCAL_LOGIN", "false")
    settings = IdentitySettings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert not settings.local_login
    (config,) = settings.provider_configs()
    assert (config.id, config.preset, config.allowed_email_domains) == (
        "gitlab",
        Preset.GITLAB,
        ("localhost.company", "acme.dev"),
    )


def test_org_role_rules() -> None:
    check_role_change(actor=OrgRole.ADMINISTRATOR, current=OrgRole.MEMBER, new=OrgRole.ADMINISTRATOR, owners=1)
    with pytest.raises(OrgRuleError, match="Only an Owner"):
        check_role_change(actor=OrgRole.ADMINISTRATOR, current=OrgRole.MEMBER, new=OrgRole.OWNER, owners=1)
    with pytest.raises(OrgRuleError, match="at least one Owner"):
        check_role_change(actor=OrgRole.OWNER, current=OrgRole.OWNER, new=OrgRole.MEMBER, owners=1)
    check_role_change(actor=OrgRole.OWNER, current=OrgRole.OWNER, new=OrgRole.MEMBER, owners=2)
    with pytest.raises(OrgRuleError):
        check_removal(actor=OrgRole.ADMINISTRATOR, target=OrgRole.OWNER, owners=2, self_removal=False)
    with pytest.raises(OrgRuleError):
        check_invite_role(actor=OrgRole.ADMINISTRATOR, role=OrgRole.OWNER)
    assert slugify("Localhost Company — Ünïcode!") == "localhost-company-unicode"


def test_instance_rules() -> None:
    assert clean_endpoint(" http://prod.agentos:7777/ ") == "http://prod.agentos:7777"
    for bad in ("ftp://x", "prod.agentos", "http://x/?q=1"):
        with pytest.raises(InstanceRuleError):
            clean_endpoint(bad)
    assert check_slug("Prod-AgentOS") == "prod-agentos"
    with pytest.raises(InstanceRuleError):
        check_slug("ins_x")
    assert slug_from("Prod AgentOS!") == "prod-agentos"
    assert version_supported("3.1.12")
    assert version_supported("3.2.0rc1")
    assert not version_supported("3.0.9")
    assert minor("3.1.12") == (3, 1)
    env, python = config_snippet(
        os_id="os-1", issuer="https://cp", public_pem="-----A-----\nxyz\n", user_isolation=True
    )
    assert env == 'JWT_VERIFICATION_KEY="-----A-----\\nxyz"'
    assert 'audience="os-1"' in python
    assert "user_isolation=True" in python


def test_audit_summaries_and_partitions() -> None:
    entry = AuditEntry(action="x", actor=ANONYMOUS, resource_display="role Operator", fields={"keys": "a, b"})
    assert render_summary("{actor} changed {resource}: {keys} {missing}", entry) == (
        "Someone changed role Operator: a, b {missing}"
    )
    assert render_summary(None, entry) == "Someone: x role Operator"
    months = partitions_to_create(datetime(2026, 12, 15, tzinfo=UTC), 1)
    assert [name for name, _, _ in months] == ["audit_events_y2026m12", "audit_events_y2027m01"]
    assert months[1][2] == datetime(2027, 2, 1, tzinfo=UTC)
    assert partition_expired(datetime(2025, 9, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC), 400)
    assert not partition_expired(datetime(2025, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC), 400)
    bound = "FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00')"
    assert upper_bound(bound) == datetime(2026, 11, 1, tzinfo=UTC)
    assert upper_bound("DEFAULT") is None


def test_gitlab_url_scheme_and_host_ignore_case() -> None:
    mixed = resolve_provider(
        "gl", preset=Preset.GITLAB, client_id="c", client_secret=None, base_url="HTTPS://GitLab.com/"
    )
    assert (mixed.issuer, mixed.base_url) == ("https://gitlab.com", None)
    hosted = resolve_provider(
        "gl", preset=Preset.GITLAB, client_id="c", client_secret=None, base_url="https://Git.Corp.test/GitLab"
    )
    assert hosted.issuer == "https://git.corp.test/GitLab"
