"""TLS helpers shared by every endpoint (database, cache, OTLP, outbound HTTPS)."""

from __future__ import annotations

import contextlib
import os
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agnostic_kernel.settings import OutboundTlsSettings, SslMode, TlsOptions


@dataclass(frozen=True, slots=True)
class ClientCertificate:
    """A client certificate chain and its private key, both PEM (mutual TLS)."""

    cert_pem: str
    key_pem: str


def load_client_certificate(context: ssl.SSLContext, certificate: ClientCertificate) -> None:
    """Load PEM text into ``context``.

    :mod:`ssl` only reads certificate chains from files, so the PEM is written to a private temporary file and
    removed again straight after loading.
    """
    fd, name = tempfile.mkstemp(prefix="agnostic-mtls-", suffix=".pem")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            _ = handle.write(certificate.cert_pem.strip() + "\n" + certificate.key_pem.strip() + "\n")
        context.load_cert_chain(certfile=str(path))
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def outbound_ssl_context(
    settings: OutboundTlsSettings,
    *,
    extra_ca_pem: str | None = None,
    client_certificate: ClientCertificate | None = None,
    verify: bool = True,
) -> ssl.SSLContext:
    """Client context for outbound HTTPS: system trust + ``AGNOSTIC_TLS__CA_FILE`` + an endpoint's own CA bundle.

    ``verify=False`` still encrypts (and still presents the client certificate) without validating the server.
    """
    context = ssl.create_default_context()
    if settings.ca_file is not None:
        context.load_verify_locations(cafile=str(settings.ca_file))
    if extra_ca_pem:
        context.load_verify_locations(cadata=extra_ca_pem)
    if client_certificate is not None:
        load_client_certificate(context, client_certificate)
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def endpoint_ssl_context(settings: OutboundTlsSettings, tls: TlsOptions) -> ssl.SSLContext:
    """Outbound context for an endpoint configured with file-based :class:`TlsOptions` (KMS, Vault)."""
    context = outbound_ssl_context(settings)
    if tls.ca_file is not None:
        context.load_verify_locations(cafile=str(tls.ca_file))
    if tls.cert_file is not None:
        context.load_cert_chain(certfile=str(tls.cert_file), keyfile=str(tls.key_file) if tls.key_file else None)
    return context


def build_ssl_context(tls: TlsOptions, *, verify: bool = True, check_hostname: bool = True) -> ssl.SSLContext:
    """Create a client SSL context from endpoint TLS options.

    ``verify=False`` encrypts without validating the server certificate (libpq ``require``).
    """
    context = ssl.create_default_context(cafile=str(tls.ca_file) if tls.ca_file else None)
    if tls.cert_file:
        context.load_cert_chain(
            certfile=str(tls.cert_file),
            keyfile=str(tls.key_file) if tls.key_file else None,
        )
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context.check_hostname = check_hostname
    return context


def asyncpg_ssl(sslmode: SslMode, tls: TlsOptions) -> ssl.SSLContext | str:
    """Translate a libpq ``sslmode`` into what asyncpg's ``ssl`` connect argument expects.

    Without custom TLS material asyncpg understands the libpq mode names directly.
    """
    has_material = tls.ca_file is not None or tls.cert_file is not None
    if sslmode in {"disable", "allow", "prefer"} or not has_material:
        return sslmode
    if sslmode == "require":
        return build_ssl_context(tls, verify=False)
    return build_ssl_context(tls, check_hostname=sslmode == "verify-full")


def libpq_tls_params(sslmode: SslMode, tls: TlsOptions) -> dict[str, str]:
    """Connection parameters for libpq-based drivers (psycopg, used by Procrastinate)."""
    params = {"sslmode": sslmode}
    if tls.ca_file:
        params["sslrootcert"] = str(tls.ca_file)
    if tls.cert_file:
        params["sslcert"] = str(tls.cert_file)
    if tls.key_file:
        params["sslkey"] = str(tls.key_file)
    return params
