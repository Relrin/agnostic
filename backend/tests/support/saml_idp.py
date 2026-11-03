"""A SAML identity provider for tests: a key pair and self-signed certificate generated at runtime, metadata, and
signed (or deliberately broken) responses."""

from __future__ import annotations

import base64
import secrets
import zlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml.algorithms import CanonicalizationMethod
from signxml.signer import XMLSigner

SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
MD = "urn:oasis:names:tc:SAML:2.0:metadata"
DS = "http://www.w3.org/2000/09/xmldsig#"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
EXC_C14N = CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0

type Signed = Literal["assertion", "response", "none"]


def _instant(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def self_signed(common_name: str) -> tuple[str, str]:
    """``(private key PEM, certificate PEM)``."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return key_pem, certificate.public_bytes(serialization.Encoding.PEM).decode()


def decode_authn_request(location: str) -> tuple[etree._Element, str]:
    """The AuthnRequest and RelayState from an HTTP-Redirect URL."""
    query = parse_qs(urlsplit(location).query)
    xml = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), wbits=-15)
    return etree.fromstring(xml), query["RelayState"][0]


class TestIdp:
    __test__ = False  # not a pytest class

    def __init__(
        self,
        entity_id: str = "https://idp.localhost.test/saml",
        sso_url: str = "https://idp.localhost.test/saml/sso",
    ) -> None:
        self.entity_id = entity_id
        self.sso_url = sso_url
        self.key_pem, self.cert_pem = self_signed("Test IdP")

    @property
    def cert_body(self) -> str:
        return "".join(line for line in self.cert_pem.splitlines() if "-----" not in line)

    def metadata(self) -> str:
        entity = etree.Element(_q(MD, "EntityDescriptor"), nsmap={"md": MD, "ds": DS}, entityID=self.entity_id)
        descriptor = etree.SubElement(
            entity, _q(MD, "IDPSSODescriptor"), protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"
        )
        key = etree.SubElement(descriptor, _q(MD, "KeyDescriptor"), use="signing")
        info = etree.SubElement(key, _q(DS, "KeyInfo"))
        data = etree.SubElement(info, _q(DS, "X509Data"))
        certificate = etree.SubElement(data, _q(DS, "X509Certificate"))
        certificate.text = self.cert_body
        for binding in ("HTTP-POST", "HTTP-Redirect"):
            _ = etree.SubElement(
                descriptor,
                _q(MD, "SingleSignOnService"),
                Binding=f"urn:oasis:names:tc:SAML:2.0:bindings:{binding}",
                Location=self.sso_url,
            )
        return etree.tostring(entity, xml_declaration=True, encoding="UTF-8").decode()

    def assertion(
        self,
        *,
        request_id: str,
        acs_url: str,
        audience: str,
        name_id: str,
        attributes: Mapping[str, Sequence[str]],
        now: datetime | None = None,
        lifetime: timedelta = timedelta(minutes=5),
        assertion_id: str | None = None,
        issuer: str | None = None,
    ) -> etree._Element:
        now = now or datetime.now(UTC)
        until = _instant(now + lifetime)
        assertion = etree.Element(
            _q(SAML, "Assertion"),
            nsmap={"saml": SAML},
            ID=assertion_id or f"_a{secrets.token_hex(16)}",
            Version="2.0",
            IssueInstant=_instant(now),
        )
        etree.SubElement(assertion, _q(SAML, "Issuer")).text = issuer or self.entity_id
        subject = etree.SubElement(assertion, _q(SAML, "Subject"))
        etree.SubElement(
            subject, _q(SAML, "NameID"), Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
        ).text = name_id
        confirmation = etree.SubElement(subject, _q(SAML, "SubjectConfirmation"), Method=BEARER)
        _ = etree.SubElement(
            confirmation,
            _q(SAML, "SubjectConfirmationData"),
            InResponseTo=request_id,
            NotOnOrAfter=until,
            Recipient=acs_url,
        )
        conditions = etree.SubElement(
            assertion, _q(SAML, "Conditions"), NotBefore=_instant(now - timedelta(seconds=5)), NotOnOrAfter=until
        )
        restriction = etree.SubElement(conditions, _q(SAML, "AudienceRestriction"))
        etree.SubElement(restriction, _q(SAML, "Audience")).text = audience
        statement = etree.SubElement(assertion, _q(SAML, "AttributeStatement"))
        for name, values in attributes.items():
            attribute = etree.SubElement(statement, _q(SAML, "Attribute"), Name=name)
            for value in values:
                etree.SubElement(attribute, _q(SAML, "AttributeValue")).text = value
        return assertion

    def sign(
        self, element: etree._Element, *, key_pem: str | None = None, cert_pem: str | None = None
    ) -> etree._Element:
        signer = XMLSigner(c14n_algorithm=EXC_C14N)
        return signer.sign(
            element,
            key=key_pem or self.key_pem,
            cert=cert_pem or self.cert_pem,
            reference_uri=element.get("ID"),
        )

    def response(
        self,
        assertion: etree._Element,
        *,
        request_id: str,
        acs_url: str,
        signed: Signed = "assertion",
        issuer: str | None = None,
    ) -> etree._Element:
        response = etree.Element(
            _q(SAMLP, "Response"),
            nsmap={"samlp": SAMLP, "saml": SAML},
            ID=f"_r{secrets.token_hex(16)}",
            Version="2.0",
            IssueInstant=_instant(datetime.now(UTC)),
            Destination=acs_url,
            InResponseTo=request_id,
        )
        etree.SubElement(response, _q(SAML, "Issuer")).text = issuer or self.entity_id
        status = etree.SubElement(response, _q(SAMLP, "Status"))
        _ = etree.SubElement(status, _q(SAMLP, "StatusCode"), Value=SUCCESS)
        response.append(self.sign(assertion) if signed == "assertion" else assertion)
        return self.sign(response) if signed == "response" else response

    def encoded(self, response: etree._Element) -> str:
        return base64.b64encode(etree.tostring(response)).decode()

    def sign_in(
        self,
        *,
        request_id: str,
        acs_url: str,
        audience: str,
        name_id: str,
        attributes: Mapping[str, Sequence[str]],
        signed: Signed = "assertion",
    ) -> str:
        """A complete base64 ``SAMLResponse`` for an AuthnRequest."""
        assertion = self.assertion(
            request_id=request_id, acs_url=acs_url, audience=audience, name_id=name_id, attributes=attributes
        )
        return self.encoded(self.response(assertion, request_id=request_id, acs_url=acs_url, signed=signed))
