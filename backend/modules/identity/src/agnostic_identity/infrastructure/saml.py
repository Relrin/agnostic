"""SAML 2.0 service provider: AuthnRequests (HTTP-Redirect), response validation, SP and IdP metadata.

Responses are validated with ``signxml`` and read **only from the element the signature covers**: a valid signature
on some other part of the document (XML signature wrapping) doesn't vouch for the assertion that gets used. The
document must contain exactly one assertion; encrypted assertions and IdP-initiated sign-ins (no ``InResponseTo``)
are refused. XML is parsed without network access, entity expansion, DTDs or huge-tree mode.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import zlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from lxml import etree
from signxml.exceptions import SignXMLException
from signxml.verifier import SignatureConfiguration, XMLVerifier

from agnostic_identity.application.ports import CertificateInfo, IdpMetadata, SpEndpoints
from agnostic_identity.domain.providers import ProviderConfigError, SamlAssertion, SamlIdp, SsoError
from agnostic_identity.infrastructure.signin_clients import SsoHttp
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
MD = "urn:oasis:names:tc:SAML:2.0:metadata"
DS = "http://www.w3.org/2000/09/xmldsig#"
NS = {"samlp": SAMLP, "saml": SAML, "md": MD, "ds": DS}
STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
HTTP_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
HTTP_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
CLOCK_SKEW = timedelta(seconds=90)
MAX_RESPONSE_BYTES = 512 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
_PEM_ARMOR = re.compile(r"-----(BEGIN|END) CERTIFICATE-----")

type Element = etree._Element  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
        dtd_validation=False,
        remove_pis=True,
    )


def parse_xml(data: bytes) -> Element:
    """Untrusted XML: no DOCTYPE at all (so no entity tricks), no network, bounded size."""
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("DOCTYPE is not allowed")
    root = etree.fromstring(data, parser=_parser())
    if root.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is not allowed")
    return root


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _instant(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _invalid(detail: str, code: str = "saml_invalid") -> SsoError:
    log.warning("identity.saml_rejected", code=code, detail=detail)
    return SsoError(code, f"The SAML sign-in response was refused: {detail}.")


def _check_window(not_before: datetime | None, not_after: datetime | None, now: datetime) -> None:
    if not_before is not None and now < not_before - CLOCK_SKEW:
        raise _invalid("the assertion isn't valid yet", "saml_expired")
    if not_after is not None and now >= not_after + CLOCK_SKEW:
        raise _invalid("the assertion expired", "saml_expired")


def _confirmed_until(assertion: Element, sp: SpEndpoints, *, request_id: str, now: datetime) -> list[datetime]:
    """Bearer subject confirmations: for this ACS, answering this request, still valid."""
    expiries: list[datetime] = []
    for confirmation in assertion.findall("saml:Subject/saml:SubjectConfirmation", NS):
        details = confirmation.find("saml:SubjectConfirmationData", NS)
        if confirmation.get("Method") != BEARER or details is None:
            continue
        if details.get("Recipient") != sp.acs_url:
            raise _invalid("the assertion is meant for a different recipient")
        if details.get("InResponseTo") != request_id:
            raise SsoError("state_mismatch", "The SAML response doesn't answer this sign-in. Start again.")
        not_after = _time(details.get("NotOnOrAfter"))
        if not_after is None:
            raise _invalid("the subject confirmation has no NotOnOrAfter")
        _check_window(_time(details.get("NotBefore")), not_after, now)
        expiries.append(not_after)
    if not expiries:
        raise _invalid("the assertion has no bearer subject confirmation")
    return expiries


def _conditions_until(assertion: Element, sp: SpEndpoints, *, now: datetime) -> list[datetime]:
    """The validity window and every audience restriction (each must name this SP)."""
    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise _invalid("the assertion has no conditions")
    not_after = _time(conditions.get("NotOnOrAfter"))
    _check_window(_time(conditions.get("NotBefore")), not_after, now)
    restrictions = conditions.findall("saml:AudienceRestriction", NS)
    if not restrictions:
        raise _invalid("the assertion has no audience restriction", "saml_audience")
    for restriction in restrictions:
        audiences = {(item.text or "").strip() for item in restriction.findall("saml:Audience", NS)}
        if sp.entity_id not in audiences:
            raise _invalid("the assertion is meant for a different service (audience)", "saml_audience")
    return [not_after] if not_after is not None else []


def _attributes(assertion: Element) -> dict[str, tuple[str, ...]]:
    """Attribute values by ``Name`` and by ``FriendlyName``."""
    attributes: dict[str, tuple[str, ...]] = {}
    for attribute in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        values = tuple(
            text for value in attribute.findall("saml:AttributeValue", NS) if (text := (value.text or "").strip())
        )
        for key in (attribute.get("Name"), attribute.get("FriendlyName")):
            if key and key not in attributes:
                attributes[key] = values
    return attributes


class XmlSamlServiceProvider:
    def __init__(self, http: SsoHttp) -> None:
        self._http = http.client

    # ------------------------------------------------------------------ AuthnRequest
    def authn_request(self, idp: SamlIdp, sp: SpEndpoints, *, relay_state: str) -> tuple[str, str]:
        request_id = f"_{secrets.token_hex(20)}"
        request = etree.Element(
            _q(SAMLP, "AuthnRequest"),
            nsmap={"samlp": SAMLP, "saml": SAML},
            ID=request_id,
            Version="2.0",
            IssueInstant=_instant(datetime.now(UTC)),
            Destination=idp.sso_url,
            AssertionConsumerServiceURL=sp.acs_url,
            ProtocolBinding=HTTP_POST,
        )
        issuer = etree.SubElement(request, _q(SAML, "Issuer"))
        issuer.text = sp.entity_id
        _ = etree.SubElement(request, _q(SAMLP, "NameIDPolicy"), Format=idp.name_id_format, AllowCreate="true")
        compressor = zlib.compressobj(wbits=-15)  # raw DEFLATE, as the HTTP-Redirect binding requires
        deflated = compressor.compress(etree.tostring(request)) + compressor.flush()
        query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode(), "RelayState": relay_state})
        separator = "&" if "?" in idp.sso_url else "?"
        return f"{idp.sso_url}{separator}{query}", request_id

    # ------------------------------------------------------------------ Response
    def parse_response(
        self, idp: SamlIdp, sp: SpEndpoints, saml_response: str, *, request_id: str, now: datetime | None = None
    ) -> SamlAssertion:
        try:
            data = base64.b64decode("".join(saml_response.split()), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _invalid("it isn't base64") from exc
        if len(data) > MAX_RESPONSE_BYTES:
            raise _invalid("it is too large")
        try:
            root = parse_xml(data)
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise _invalid(f"malformed XML ({exc})") from exc
        if root.tag != _q(SAMLP, "Response"):
            raise _invalid("it isn't a SAML Response")

        status = root.find("samlp:Status/samlp:StatusCode", NS)
        if status is None or status.get("Value") != STATUS_SUCCESS:
            raise SsoError("provider_denied", "The identity provider didn't sign you in.")
        destination = root.get("Destination")
        if destination and destination != sp.acs_url:
            raise _invalid("its Destination is not this service")
        if root.find(f".//{{{SAML}}}EncryptedAssertion") is not None:
            raise _invalid("encrypted assertions aren't supported (turn assertion encryption off at the IdP)")
        if len(root.findall(f".//{{{SAML}}}Assertion")) != 1:
            raise _invalid("it must contain exactly one assertion", "saml_signature")

        assertion = self._signed_assertion(root, data, idp)
        response_issuer = root.findtext("saml:Issuer", namespaces=NS)
        if response_issuer is not None and response_issuer.strip() != idp.entity_id:
            raise _invalid("it comes from a different IdP")
        return self._validated(assertion, idp, sp, request_id=request_id, now=now or datetime.now(UTC))

    def _verify(self, data: bytes, idp: SamlIdp, location: str) -> Element:
        config = SignatureConfiguration(location=location, expect_references=1)
        errors: list[str] = []
        for pem in idp.certificates:
            try:
                result = XMLVerifier().verify(  # pyright: ignore[reportUnknownMemberType]
                    data, x509_cert=pem, parser=_parser(), expect_config=config
                )
            except SignXMLException as exc:
                errors.append(str(exc))
                continue
            signed = result.signed_xml if not isinstance(result, list) else None
            if signed is None:
                break
            return signed
        raise _invalid(f"the signature doesn't verify ({'; '.join(errors) or 'no signed data'})", "saml_signature")

    def _signed_assertion(self, root: Element, data: bytes, idp: SamlIdp) -> Element:
        """The assertion as covered by a signature on the Response or on the Assertion itself."""
        if root.find("ds:Signature", NS) is not None:
            signed = self._verify(data, idp, "./")
            if signed.tag != _q(SAMLP, "Response") or signed.get("ID") != root.get("ID"):
                raise _invalid("the signature covers something other than the Response", "saml_signature")
            assertion = signed.find("saml:Assertion", NS)
            if assertion is None:
                raise _invalid("the signed Response has no assertion", "saml_signature")
            return assertion
        candidate = root.find("saml:Assertion", NS)
        if candidate is None or candidate.find("ds:Signature", NS) is None:
            raise _invalid("neither the Response nor the Assertion is signed", "saml_signature")
        signed = self._verify(data, idp, f"./{{{SAML}}}Assertion/")
        if signed.tag != _q(SAML, "Assertion") or signed.get("ID") != candidate.get("ID"):
            raise _invalid("the signature covers a different element than the assertion", "saml_signature")
        return signed

    def _validated(
        self, assertion: Element, idp: SamlIdp, sp: SpEndpoints, *, request_id: str, now: datetime
    ) -> SamlAssertion:
        assertion_id = assertion.get("ID")
        if not assertion_id:
            raise _invalid("the assertion has no ID")
        issuer = (assertion.findtext("saml:Issuer", namespaces=NS) or "").strip()
        if issuer != idp.entity_id:
            raise _invalid(f"the assertion was issued by {issuer!r}, not {idp.entity_id!r}")
        name_id = assertion.find("saml:Subject/saml:NameID", NS)
        if name_id is None or not (name_id.text or "").strip():
            raise _invalid("the assertion has no NameID")
        expiries = [
            *_confirmed_until(assertion, sp, request_id=request_id, now=now),
            *_conditions_until(assertion, sp, now=now),
        ]
        return SamlAssertion(
            id=assertion_id,
            issuer=issuer,
            name_id=(name_id.text or "").strip(),
            name_id_format=name_id.get("Format"),
            attributes=_attributes(assertion),
            not_on_or_after=min(expiries),
        )

    # ------------------------------------------------------------------ metadata
    def sp_metadata(self, sp: SpEndpoints, *, name_id_format: str) -> str:
        entity = etree.Element(_q(MD, "EntityDescriptor"), nsmap={"md": MD}, entityID=sp.entity_id)
        descriptor = etree.SubElement(
            entity,
            _q(MD, "SPSSODescriptor"),
            AuthnRequestsSigned="false",
            WantAssertionsSigned="true",
            protocolSupportEnumeration=SAMLP,
        )
        name_id = etree.SubElement(descriptor, _q(MD, "NameIDFormat"))
        name_id.text = name_id_format
        _ = etree.SubElement(
            descriptor,
            _q(MD, "AssertionConsumerService"),
            Binding=HTTP_POST,
            Location=sp.acs_url,
            index="0",
            isDefault="true",
        )
        return etree.tostring(entity, xml_declaration=True, encoding="UTF-8", pretty_print=True).decode()

    def parse_idp_metadata(self, xml: str) -> IdpMetadata:
        try:
            root = parse_xml(xml.strip().encode())
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise ProviderConfigError(f"The IdP metadata isn't valid XML ({exc}).") from exc
        entities = [root] if root.tag == _q(MD, "EntityDescriptor") else root.findall(".//md:EntityDescriptor", NS)
        entity = next((item for item in entities if item.find("md:IDPSSODescriptor", NS) is not None), None)
        if entity is None:
            raise ProviderConfigError("The metadata has no IdP (IDPSSODescriptor).")
        descriptor = entity.find("md:IDPSSODescriptor", NS)
        assert descriptor is not None
        sso_url = next(
            (
                service.get("Location", "")
                for service in descriptor.findall("md:SingleSignOnService", NS)
                if service.get("Binding") == HTTP_REDIRECT
            ),
            "",
        )
        if not sso_url:
            raise ProviderConfigError("The IdP doesn't offer the HTTP-Redirect binding for single sign-on.")
        certificates: list[str] = []
        for key in descriptor.findall("md:KeyDescriptor", NS):
            if key.get("use") not in {None, "signing"}:
                continue
            certificates.extend(
                self.normalize_certificate(item.text or "") for item in key.iterfind(".//ds:X509Certificate", NS)
            )
        if not certificates:
            raise ProviderConfigError("The metadata has no signing certificate.")
        return IdpMetadata(
            entity_id=entity.get("entityID", ""),
            sso_url=sso_url,
            certificates=tuple(dict.fromkeys(certificates)),
        )

    async def fetch_idp_metadata(self, url: str) -> str:
        try:
            response = await self._http.get(url, headers={"Accept": "application/samlmetadata+xml, application/xml"})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderConfigError(f"Can't read the IdP metadata at {url} ({exc}).") from exc
        if len(response.content) > MAX_METADATA_BYTES:
            raise ProviderConfigError("The IdP metadata is too large.")
        return response.text

    def normalize_certificate(self, text: str) -> str:
        body = "".join(_PEM_ARMOR.sub("", text).split())
        try:
            certificate = x509.load_der_x509_certificate(base64.b64decode(body, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise ProviderConfigError("A signing certificate isn't a valid X.509 certificate.") from exc
        return certificate.public_bytes(serialization.Encoding.PEM).decode()

    def describe_certificate(self, pem: str) -> CertificateInfo:
        try:
            certificate = x509.load_pem_x509_certificate(pem.encode())
        except ValueError as exc:
            raise ProviderConfigError("Not a PEM certificate.") from exc
        fingerprint = certificate.fingerprint(hashes.SHA256()).hex(":").upper()
        return CertificateInfo(
            subject=certificate.subject.rfc4514_string(),
            not_after=certificate.not_valid_after_utc,
            fingerprint_sha256=fingerprint,
        )
