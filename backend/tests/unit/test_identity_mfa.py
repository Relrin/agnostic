"""Second factors: HOTP/TOTP against the RFC test vectors, recovery codes, and the auth policy rules."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from agnostic_identity.domain import totp
from agnostic_identity.domain.mfa import (
    RECOVERY_CODE_COUNT,
    Factor,
    FactorKind,
    MfaMethod,
    clean_label,
    methods_for,
    new_recovery_codes,
    normalize_recovery_code,
)
from agnostic_identity.domain.policy import AuthPolicy, InvalidPolicyError, MfaPolicy, check_lifetimes, is_recent
from agnostic_identity.domain.users import SessionPolicy

RFC_SECRET = b"12345678901234567890"


def test_hotp_rfc4226_vectors() -> None:
    expected = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
    assert [totp.hotp(RFC_SECRET, counter) for counter in range(10)] == expected


@pytest.mark.parametrize(
    ("at", "code"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_rfc6238_sha1_vectors(at: int, code: str) -> None:
    assert totp.totp(RFC_SECRET, at, digits=8) == code


def test_verify_accepts_one_step_of_drift() -> None:
    now = 1_700_000_000.0
    code = totp.totp(RFC_SECRET, now)
    step = totp.time_step(now)
    assert totp.verify(RFC_SECRET, code, now) == step
    assert totp.verify(RFC_SECRET, code, now + 30) == step
    assert totp.verify(RFC_SECRET, code, now - 30) == step
    assert totp.verify(RFC_SECRET, code, now + 90) is None
    assert totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", now) == step  # spaces as typed
    assert totp.verify(RFC_SECRET, "12345", now) is None
    assert totp.verify(RFC_SECRET, "abcdef", now) is None


def test_secrets_and_otpauth_uri() -> None:
    secret = totp.new_secret()
    assert len(totp.decode_secret(secret)) == totp.SECRET_BYTES
    assert totp.decode_secret(secret.lower()) == totp.decode_secret(secret)
    with pytest.raises(totp.InvalidSecretError):
        _ = totp.decode_secret("not base32!")
    uri = urlsplit(totp.otpauth_uri(secret, account="ada@localhost.company", issuer="Agnostic"))
    assert (uri.scheme, uri.netloc, uri.path) == ("otpauth", "totp", "/Agnostic:ada@localhost.company")
    query = parse_qs(uri.query)
    assert query["secret"] == [secret]
    assert query["issuer"] == ["Agnostic"]
    assert query["digits"] == ["6"]


def test_recovery_codes() -> None:
    codes = new_recovery_codes()
    assert len(codes) == RECOVERY_CODE_COUNT
    assert len(set(codes)) == RECOVERY_CODE_COUNT
    for code in codes:
        groups = code.split("-")
        assert [len(group) for group in groups] == [4, 4, 4, 4]
        assert not set(code) & set("ilo01")
    assert normalize_recovery_code(f" {codes[0].upper().replace('-', ' ')} ") == codes[0].replace("-", "")


def test_methods_offered() -> None:
    now = datetime.now(UTC)
    app = Factor("crd_1", FactorKind.TOTP, "Phone", now, None)
    key = Factor("crd_2", FactorKind.WEBAUTHN, "YubiKey", now, None)
    assert methods_for([], has_recovery_codes=False) == ()
    assert methods_for([key, app], has_recovery_codes=True) == (
        MfaMethod.TOTP,
        MfaMethod.WEBAUTHN,
        MfaMethod.RECOVERY_CODE,
    )
    assert clean_label("  ", "Security key") == "Security key"
    assert clean_label(" My   key ", "x") == "My key"


def test_auth_policy_rules() -> None:
    default = SessionPolicy(idle=timedelta(hours=12), absolute=timedelta(days=7))
    policy = AuthPolicy()
    assert policy.password_allowed("usr_1")
    assert policy.session_policy(default) == default
    assert policy.enrollment_allowed
    assert not policy.mfa_required_for("owner")

    enforced = policy.updated(
        enforce_sso=True,
        break_glass_user_id="usr_owner",
        session_idle_minutes=30,
        session_absolute_hours=8,
        mfa_policy=MfaPolicy.REQUIRED_ADMINS,
    )
    assert not enforced.password_allowed("usr_1")
    assert enforced.password_allowed("usr_owner")
    assert enforced.session_policy(default) == SessionPolicy(idle=timedelta(minutes=30), absolute=timedelta(hours=8))
    assert enforced.mfa_required_for("administrator")
    assert not enforced.mfa_required_for("member")
    assert AuthPolicy(mfa_policy=MfaPolicy.REQUIRED_LOCAL).mfa_required_for(None)
    assert not AuthPolicy(mfa_policy=MfaPolicy.OFF).enrollment_allowed

    with pytest.raises(InvalidPolicyError):
        _ = policy.updated(
            enforce_sso=True,
            break_glass_user_id=None,
            session_idle_minutes=None,
            session_absolute_hours=None,
            mfa_policy=MfaPolicy.OPTIONAL,
        )
    with pytest.raises(InvalidPolicyError):
        check_lifetimes(600, 2)  # idle longer than the absolute lifetime
    with pytest.raises(InvalidPolicyError):
        check_lifetimes(1, None)


def test_recent_authentication() -> None:
    now = datetime.now(UTC)
    assert is_recent(now - timedelta(minutes=9), now)
    assert not is_recent(now - timedelta(minutes=11), now)
    assert not is_recent(None, now)
