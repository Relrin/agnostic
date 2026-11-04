"""TLS for connections to a runtime, shared by the control plane's own calls and the gateway.

Server trust is the system store plus the organization CA (``AGNOSTIC_TLS__CA_FILE``) plus the instance's own
bundle; the optional client certificate gives mutual TLS.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass

from agnostic_instances.domain.instances import Instance
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.settings import OutboundTlsSettings
from agnostic_kernel.tls import ClientCertificate, load_client_certificate, outbound_ssl_context


@dataclass(frozen=True, slots=True)
class ConnectionTls:
    """Everything a connection to one runtime needs for TLS; the client key stays sealed until used."""

    tls_verify: bool = True
    ca_bundle_pem: str | None = None
    client_cert_pem: str | None = None
    client_key_sealed: str | None = None

    @property
    def fingerprint(self) -> str:
        """Changes whenever any of it changes (pooled clients are keyed by it)."""
        parts = (
            str(self.tls_verify),
            self.ca_bundle_pem or "",
            self.client_cert_pem or "",
            self.client_key_sealed or "",
        )
        return "|".join(parts)


def connection_tls(instance: Instance) -> ConnectionTls:
    return ConnectionTls(
        tls_verify=instance.tls_verify,
        ca_bundle_pem=instance.ca_bundle_pem,
        client_cert_pem=instance.client_cert_pem,
        client_key_sealed=instance.client_key_sealed,
    )


class ConnectionTlsFactory:
    """Builds the ``verify`` argument for httpx from :class:`ConnectionTls`."""

    def __init__(self, box: SecretBox, outbound: OutboundTlsSettings) -> None:
        self._box = box
        self._outbound = outbound

    def verify(self, tls: ConnectionTls) -> bool | ssl.SSLContext:
        certificate = None
        if tls.client_cert_pem and tls.client_key_sealed:
            key_pem = self._box.open(tls.client_key_sealed).decode()
            certificate = ClientCertificate(tls.client_cert_pem, key_pem)
        if certificate is None and tls.ca_bundle_pem is None and self._outbound.ca_file is None:
            return tls.tls_verify
        return outbound_ssl_context(
            self._outbound,
            extra_ca_pem=tls.ca_bundle_pem if tls.tls_verify else None,
            client_certificate=certificate,
            verify=tls.tls_verify,
        )


def check_client_certificate(cert_pem: str, key_pem: str) -> None:
    """Fail with :class:`ValueError` unless the certificate and key are PEM and belong together."""
    context = ssl.create_default_context()
    try:
        load_client_certificate(context, ClientCertificate(cert_pem, key_pem))
    except (ssl.SSLError, OSError) as exc:
        msg = "The client certificate and key must be PEM and belong together."
        raise ValueError(msg) from exc
