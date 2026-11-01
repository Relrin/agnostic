"""Settings, ids, pagination, TLS, logging redaction."""

import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from agnostic_kernel import ids
from agnostic_kernel.errors import ValidationFailedError
from agnostic_kernel.logging import REDACTED, configure_logging, get_logger, redact_secrets
from agnostic_kernel.pagination import Page, PageParams, decode_cursor, encode_cursor, page_params
from agnostic_kernel.settings import (
    DatabaseSettings,
    LogSettings,
    Settings,
    TlsOptions,
    backend_of,
    module_settings_config,
    redact_url,
)
from agnostic_kernel.testing import make_settings
from agnostic_kernel.tls import asyncpg_ssl, build_ssl_context, libpq_tls_params


class TestSettings:
    def test_env_nesting_and_csv_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGNOSTIC_DATABASE__URL", "postgresql://u:p@db:5432/cp")
        monkeypatch.setenv("AGNOSTIC_DATABASE__SSLMODE", "verify-full")
        monkeypatch.setenv("AGNOSTIC_MODULES__DISABLED", "assistant, sources")
        monkeypatch.setenv("AGNOSTIC_REDIS__SENTINELS", "s1:26379,s2")
        monkeypatch.setenv("AGNOSTIC_HTTP__CORS_ORIGINS", "https://a.example")
        settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
        assert settings.database.sslmode == "verify-full"
        assert settings.database.backend == "postgresql"
        assert settings.modules.disabled == ["assistant", "sources"]
        assert settings.redis.sentinels == ["s1:26379", "s2"]
        assert settings.http.cors_origins == ["https://a.example"]

    def test_toml_file_is_a_source(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config = tmp_path / "agnostic.toml"
        config.write_text('env = "development"\n[http]\nport = 9001\n', encoding="utf-8")
        monkeypatch.setenv("AGNOSTIC_CONFIG_FILE", str(config))
        settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
        assert settings.env == "development"
        assert settings.http.port == 9001

    def test_redacted_hides_passwords(self) -> None:
        settings = make_settings("postgresql://agnostic:hunter2@db/cp", "redis://:s3cret@cache:6379/0")
        dumped = str(settings.redacted())
        assert "hunter2" not in dumped
        assert "s3cret" not in dumped
        assert "agnostic:***@db" in dumped

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("postgresql://h/db", "postgresql"),
            ("postgres://h/db", "postgresql"),
            ("postgresql+asyncpg://h/db", "postgresql"),
            ("sqlite:///x.db", "sqlite"),
            ("sqlite+aiosqlite:///:memory:", "sqlite"),
        ],
    )
    def test_backend_of(self, url: str, expected: str) -> None:
        assert backend_of(url) == expected

    def test_unknown_backend_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unsupported database URL scheme"):
            DatabaseSettings(url="mysql://h/db")  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(
        ("url", "mode", "expected"),
        [
            ("postgresql://h/db", "auto", "worker"),
            ("sqlite:///x.db", "auto", "embedded"),
            ("postgresql://h/db", "embedded", "embedded"),
        ],
    )
    def test_job_mode(self, url: str, mode: str, expected: str) -> None:
        assert make_settings(url, jobs={"mode": mode}).job_mode() == expected

    def test_redact_url_without_password(self) -> None:
        assert redact_url("redis://cache:6379/0") == "redis://cache:6379/0"

    def test_module_settings_namespace(self) -> None:
        assert module_settings_config("gateway").get("env_prefix") == "AGNOSTIC_GATEWAY__"


class TestIds:
    def test_new_id_round_trip(self) -> None:
        value = ids.new_id("usr")
        assert value.startswith("usr_")
        assert ids.parse_id(value, "usr") == value
        assert abs(ids.id_timestamp(value) - datetime.now(UTC)) < timedelta(seconds=5)

    def test_ids_sort_by_creation(self) -> None:
        first, second = ids.new_id("ins"), ids.new_id("ins")
        assert first < second

    def test_wrong_prefix_or_shape(self) -> None:
        value = ids.new_id("usr")
        with pytest.raises(ids.InvalidIdError):
            ids.parse_id(value, "ins")
        with pytest.raises(ids.InvalidIdError):
            ids.parse_id("usr_nope", "usr")

    @pytest.mark.parametrize("prefix", ["", "U", "toolong", "a1"])
    def test_invalid_prefix(self, prefix: str) -> None:
        with pytest.raises(ValueError, match="id prefix"):
            ids.new_id(prefix)

    def test_pydantic_type(self) -> None:
        adapter = TypeAdapter(ids.id_type("grp"))
        value = ids.new_id("grp")
        assert adapter.validate_python(value) == value
        with pytest.raises(ValidationError):
            adapter.validate_python("usr_" + value[4:])


class TestPagination:
    def test_cursor_round_trip(self) -> None:
        cursor = encode_cursor({"after": "hel_01", "n": 3})
        assert "=" not in cursor
        assert decode_cursor(cursor) == {"after": "hel_01", "n": 3}

    @pytest.mark.parametrize("cursor", ["!!!", "WzFd", "bm90LWpzb24"])  # garbage, a JSON list, not JSON
    def test_bad_cursor(self, cursor: str) -> None:
        with pytest.raises(ValidationFailedError):
            decode_cursor(cursor)

    def test_params(self) -> None:
        params = page_params(limit=10, cursor=encode_cursor({"after": "x"}))
        assert params.limit == 10
        assert params.position() == {"after": "x"}
        assert PageParams().position() is None

    def test_envelope(self) -> None:
        page = Page[int](data=[1, 2], next_cursor="c")
        assert page.model_dump() == {"data": [1, 2], "next_cursor": "c", "total_estimate": None}


class TestTls:
    def test_modes_without_material_pass_through(self) -> None:
        assert asyncpg_ssl("verify-full", TlsOptions()) == "verify-full"
        assert asyncpg_ssl("disable", TlsOptions(ca_file=Path("ca.pem"))) == "disable"

    def test_libpq_params(self) -> None:
        tls = TlsOptions(ca_file=Path("ca.pem"), cert_file=Path("c.pem"), key_file=Path("k.pem"))
        assert libpq_tls_params("verify-ca", tls) == {
            "sslmode": "verify-ca",
            "sslrootcert": "ca.pem",
            "sslcert": "c.pem",
            "sslkey": "k.pem",
        }

    def test_contexts(self) -> None:
        unverified = build_ssl_context(TlsOptions(), verify=False)
        assert unverified.verify_mode == ssl.CERT_NONE
        no_hostname = build_ssl_context(TlsOptions(), check_hostname=False)
        assert not no_hostname.check_hostname
        assert no_hostname.verify_mode == ssl.CERT_REQUIRED


class TestLogging:
    def test_redacts_nested_secrets(self) -> None:
        event = {"event": "x", "password": "p", "nested": {"api_key": "k", "ok": 1}, "user": "u"}
        out = redact_secrets(None, "info", event)
        assert out["password"] == REDACTED
        assert out["nested"] == {"api_key": REDACTED, "ok": 1}
        assert out["user"] == "u"

    @pytest.mark.parametrize("fmt", ["json", "console"])
    def test_configure(self, fmt: str, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(LogSettings(level="INFO", format=fmt))  # pyright: ignore[reportArgumentType]
        get_logger("t").info("hello_event", token="abc")
        err = capsys.readouterr().err
        assert "hello_event" in err
        assert "abc" not in err
