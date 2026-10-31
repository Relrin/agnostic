"""TLS helpers shared by every endpoint (database, cache, OTLP)."""

from __future__ import annotations

import ssl

from agnostic_kernel.settings import SslMode, TlsOptions


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
