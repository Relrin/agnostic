"""SAML service provider: response validation (signature, wrapping, audience, time, InResponseTo, replay), metadata
and AuthnRequests, against a test IdP whose key and certificate are generated at runtime."""

import base64
import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from lxml import etree

from agnostic_identity.application.ports import SpEndpoints
from agnostic_identity.application.signin import SamlReplayGuard
from agnostic_identity.domain.providers import (
    NAME_ID_PERSISTENT,
    AttributeMapping,
    ProviderConfigError,
    SamlIdp,
    SsoError,
    saml_profile,
)
from agnostic_identity.infrastructure.saml import XmlSamlServiceProvider
from agnostic_identity.infrastructure.signin_clients import SsoHttp
from agnostic_kernel.ephemeral import MemoryStore
from tests.support.saml_idp import SAML, TestIdp, decode_authn_request, self_signed

SP = SpEndpoints(
    entity_id="http://agnostic.test/api/v1/auth/sso/corp/metadata",
    acs_url="http://agnostic.test/api/v1/auth/sso/corp/acs",
)
REQUEST_ID = "_req123"
ATTRIBUTES = {"email": ["ada@localhost.company"], "displayName": ["Ada Lovelace"], "groups": ["eng", "admins"]}


@pytest.fixture(scope="module")
def idp() -> TestIdp:
    return TestIdp()


@pytest.fixture
def sp() -> XmlSamlServiceProvider:
    return XmlSamlServiceProvider(
        SsoHttp(httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404))))
    )


def config_of(idp: TestIdp, *, certificates: tuple[str, ...] | None = None) -> SamlIdp:
    return SamlIdp(
        entity_id=idp.entity_id,
        sso_url=idp.sso_url,
        certificates=certificates or (idp.cert_pem,),
        name_id_format=NAME_ID_PERSISTENT,
    )


def sign_in(idp: TestIdp, **overrides: object) -> str:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
        "acs_url": SP.acs_url,
        "audience": SP.entity_id,
        "name_id": "okta|ada",
        "attributes": ATTRIBUTES,
    }
    values.update(overrides)
    return idp.sign_in(**values)  # pyright: ignore[reportArgumentType]


def rejected(sp: XmlSamlServiceProvider, idp: TestIdp, response: str, **kwargs: object) -> SsoError:
    with pytest.raises(SsoError) as caught:
        _ = sp.parse_response(config_of(idp), SP, response, request_id=REQUEST_ID, **kwargs)  # pyright: ignore[reportArgumentType]
    return caught.value


@pytest.mark.parametrize("signed", ["assertion", "response"])
def test_valid_signed_response(sp: XmlSamlServiceProvider, idp: TestIdp, signed: str) -> None:
    assertion = sp.parse_response(config_of(idp), SP, sign_in(idp, signed=signed), request_id=REQUEST_ID)
    assert assertion.issuer == idp.entity_id
    assert assertion.name_id == "okta|ada"
    assert assertion.attributes["groups"] == ("eng", "admins")
    assert assertion.not_on_or_after > datetime.now(UTC)

    profile = saml_profile(config_of(idp), assertion)
    assert (profile.subject, profile.email, profile.display_name) == (
        "okta|ada",
        "ada@localhost.company",
        "Ada Lovelace",
    )
    assert profile.email_verified
    assert profile.claims["groups"] == ["eng", "admins"]


def test_attribute_mapping_and_rotation(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    _, other_cert = self_signed("Previous IdP key")
    mapped = SamlIdp(
        entity_id=idp.entity_id,
        sso_url=idp.sso_url,
        certificates=(other_cert, idp.cert_pem),  # the old certificate first: any listed one may sign
        attributes=AttributeMapping(email="mail", name="cn", groups="memberOf"),
    )
    response = sign_in(idp, attributes={"mail": ["grace@localhost.company"], "cn": ["Grace"], "memberOf": ["ops"]})
    profile = saml_profile(mapped, sp.parse_response(mapped, SP, response, request_id=REQUEST_ID))
    assert (profile.email, profile.display_name, profile.claims["groups"]) == (
        "grace@localhost.company",
        "Grace",
        ["ops"],
    )


def test_bad_signature(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    impostor = TestIdp(entity_id=idp.entity_id)  # same entity id, a different key
    assert rejected(sp, idp, sign_in(impostor)).code == "saml_signature"

    tampered = etree.fromstring(base64.b64decode(sign_in(idp)))
    value = tampered.find(f".//{{{SAML}}}AttributeValue")
    assert value is not None
    value.text = "mallory@localhost.company"
    assert rejected(sp, idp, base64.b64encode(etree.tostring(tampered)).decode()).code == "saml_signature"


def test_unsigned_response(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    assert rejected(sp, idp, sign_in(idp, signed="none")).code == "saml_signature"


def test_wrapped_assertion(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    """XML signature wrapping: the signed assertion is hidden, an unsigned one with the copied signature is used."""
    legit = etree.fromstring(base64.b64decode(sign_in(idp)))
    signed = legit.find(f"{{{SAML}}}Assertion")
    assert signed is not None
    evil = copy.deepcopy(signed)
    evil.set("ID", "_evil")
    name_id = evil.find(f"{{{SAML}}}Subject/{{{SAML}}}NameID")
    assert name_id is not None
    name_id.text = "okta|mallory"
    for value in evil.iter(f"{{{SAML}}}AttributeValue"):
        value.text = "mallory@localhost.company"
    legit.remove(signed)
    evil.append(signed)  # the original, still validly signed, nested inside the forged one
    legit.append(evil)
    error = rejected(sp, idp, base64.b64encode(etree.tostring(legit)).decode())
    assert error.code == "saml_signature"

    # The signature element moved into a forged sibling assertion that is the only one left: the reference no
    # longer resolves to what is used.
    forged = etree.fromstring(base64.b64decode(sign_in(idp)))
    original = forged.find(f"{{{SAML}}}Assertion")
    assert original is not None
    replacement = copy.deepcopy(original)
    replacement_name = replacement.find(f"{{{SAML}}}Subject/{{{SAML}}}NameID")
    assert replacement_name is not None
    replacement_name.text = "okta|mallory"
    forged.replace(original, replacement)
    assert rejected(sp, idp, base64.b64encode(etree.tostring(forged)).decode()).code == "saml_signature"


def test_wrong_audience_recipient_and_issuer(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    assert rejected(sp, idp, sign_in(idp, audience="https://other.example/sp")).code == "saml_audience"
    assert rejected(sp, idp, sign_in(idp, acs_url="https://other.example/acs")).code == "saml_invalid"
    other_issuer = idp.encoded(
        idp.response(
            idp.assertion(
                request_id=REQUEST_ID,
                acs_url=SP.acs_url,
                audience=SP.entity_id,
                name_id="okta|ada",
                attributes=ATTRIBUTES,
                issuer="https://evil.example/idp",
            ),
            request_id=REQUEST_ID,
            acs_url=SP.acs_url,
        )
    )
    assert rejected(sp, idp, other_issuer).code == "saml_invalid"


def test_expired_and_not_yet_valid(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    response = sign_in(idp)
    later = datetime.now(UTC) + timedelta(minutes=10)
    assert rejected(sp, idp, response, now=later).code == "saml_expired"
    earlier = datetime.now(UTC) - timedelta(minutes=10)
    assert rejected(sp, idp, response, now=earlier).code == "saml_expired"
    # Within the clock skew is fine.
    within = datetime.now(UTC) + timedelta(minutes=5, seconds=30)
    assert sp.parse_response(config_of(idp), SP, response, request_id=REQUEST_ID, now=within).name_id == "okta|ada"


def test_in_response_to_mismatch(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    assert rejected(sp, idp, sign_in(idp, request_id="_someone_elses_request")).code == "state_mismatch"


async def test_replayed_assertion() -> None:
    guard = SamlReplayGuard(MemoryStore())
    until = datetime.now(UTC) + timedelta(minutes=5)
    await guard.check("corp", "_assertion1", until)
    with pytest.raises(SsoError) as caught:
        await guard.check("corp", "_assertion1", until)
    assert caught.value.code == "saml_replayed"
    await guard.check("other", "_assertion1", until)  # per provider


def test_hostile_xml(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><samlp:Response xmlns:samlp="x">&a;</samlp:Response>'
    assert rejected(sp, idp, base64.b64encode(bomb).decode()).code == "saml_invalid"
    assert rejected(sp, idp, "not base64 at all!").code == "saml_invalid"


def test_metadata_and_authn_request(sp: XmlSamlServiceProvider, idp: TestIdp) -> None:
    parsed = sp.parse_idp_metadata(idp.metadata())
    assert (parsed.entity_id, parsed.sso_url) == (idp.entity_id, idp.sso_url)
    assert parsed.certificates == (sp.normalize_certificate(idp.cert_pem),)
    assert sp.describe_certificate(parsed.certificates[0]).subject == "CN=Test IdP"
    with pytest.raises(ProviderConfigError):
        _ = sp.parse_idp_metadata("<md:EntityDescriptor xmlns:md='urn:oasis:names:tc:SAML:2.0:metadata'/>")
    with pytest.raises(ProviderConfigError):
        _ = sp.normalize_certificate("not a certificate")

    metadata = etree.fromstring(sp.sp_metadata(SP, name_id_format=NAME_ID_PERSISTENT).encode())
    assert metadata.get("entityID") == SP.entity_id
    acs = metadata.find(".//{urn:oasis:names:tc:SAML:2.0:metadata}AssertionConsumerService")
    assert acs is not None
    assert acs.get("Location") == SP.acs_url

    url, request_id = sp.authn_request(config_of(idp), SP, relay_state="state-1")
    assert url.startswith(f"{idp.sso_url}?SAMLRequest=")
    request, relay_state = decode_authn_request(url)
    assert relay_state == "state-1"
    assert request.get("ID") == request_id
    assert request.get("AssertionConsumerServiceURL") == SP.acs_url
    assert request.findtext(f"{{{SAML}}}Issuer") == SP.entity_id
