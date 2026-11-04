"""HTTP routes: ``/api/v1/instances`` and the public JWKS documents."""

# No `from __future__ import annotations`: dishka wraps endpoints and FastAPI resolves annotations here.

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from agnostic_instances.api.schemas import (
    CapabilityOut,
    ConfigOut,
    ConnectedOut,
    ConnectIn,
    HealthOut,
    InstanceOut,
    InstanceUpdate,
    KeysOut,
    ProbeIn,
    ProbeOut,
    RotateIn,
    StepOut,
    TestReportOut,
    TokenCheckOut,
    VerifyTokenIn,
)
from agnostic_instances.application.use_cases import (
    ConnectInstance,
    ConnectRequest,
    DeleteInstance,
    GetConfig,
    GetHealth,
    GetInstance,
    GetKeys,
    InstanceChanges,
    Jwks,
    ListInstances,
    ProbeEndpoint,
    Rediscover,
    RotateKeys,
    TestConnection,
    UpdateInstance,
    VerifyToken,
)
from agnostic_instances.domain.instances import EnvTag, NetworkMode, SubClaimMode
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)
well_known = APIRouter(route_class=DishkaRoute)


@router.get("", summary="Connected AgentOS instances")
async def list_instances(principal: FromDishka[Principal], use_case: FromDishka[ListInstances]) -> list[InstanceOut]:
    return [InstanceOut.from_domain(item) for item in await use_case(principal)]


@router.post("/probe", summary="Connect wizard, step 1: discover what is at an endpoint (nothing is saved)")
async def probe_endpoint(
    body: ProbeIn, principal: FromDishka[Principal], use_case: FromDishka[ProbeEndpoint]
) -> ProbeOut:
    result = await use_case(
        principal,
        body.endpoint_url,
        tls_verify=body.tls_verify,
        ca_bundle_pem=body.ca_bundle_pem,
        client_cert_pem=body.client_cert_pem,
        client_key_pem=body.client_key_pem,
    )
    return ProbeOut.from_result(result)


@router.post(
    "", status_code=status.HTTP_201_CREATED, summary="Connect wizard, step 2: register an instance and its key pair"
)
async def connect_instance(
    body: ConnectIn, principal: FromDishka[Principal], use_case: FromDishka[ConnectInstance]
) -> ConnectedOut:
    instance, diagnosis = await use_case(
        principal,
        ConnectRequest(
            endpoint_url=body.endpoint_url,
            display_name=body.display_name,
            slug=body.slug,
            env_tag=EnvTag(body.env_tag),
            tls_verify=body.tls_verify,
            ca_bundle_pem=body.ca_bundle_pem,
            security_key=body.security_key,
            sub_claim_mode=SubClaimMode(body.sub_claim_mode),
            client_cert_pem=body.client_cert_pem,
            client_key_pem=body.client_key_pem,
        ),
    )
    return ConnectedOut(
        instance=InstanceOut.from_domain(instance),
        steps=[StepOut(id=s.id, label=s.label, status=s.status, detail=s.detail, hint=s.hint) for s in diagnosis.steps],
    )


@router.get("/{instance}", summary="One instance (by id or slug)")
async def get_instance(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[GetInstance]
) -> InstanceOut:
    return InstanceOut.from_domain(await use_case(principal, instance))


@router.patch(
    "/{instance}", summary="Change an instance's name, environment, endpoint, TLS, keys, network mode or elevation"
)
async def update_instance(
    instance: str, body: InstanceUpdate, principal: FromDishka[Principal], use_case: FromDishka[UpdateInstance]
) -> InstanceOut:
    changes = InstanceChanges(
        display_name=body.display_name,
        slug=body.slug,
        env_tag=EnvTag(body.env_tag) if body.env_tag else None,
        endpoint_url=body.endpoint_url,
        sub_claim_mode=SubClaimMode(body.sub_claim_mode) if body.sub_claim_mode else None,
        tls_verify=body.tls_verify,
        ca_bundle_pem=body.ca_bundle_pem,
        security_key=body.security_key,
        status=body.status,
        elevation_enabled=body.elevation_enabled,
        client_cert_pem=body.client_cert_pem,
        client_key_pem=body.client_key_pem,
        network_mode=NetworkMode(body.network_mode) if body.network_mode else None,
        browser_url=body.browser_url,
    )
    return InstanceOut.from_domain(await use_case(principal, instance, changes, body.version))


@router.delete(
    "/{instance}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the instance record (the runtime keeps running; its tokens stop being minted)",
)
async def delete_instance(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[DeleteInstance],
    confirm: Annotated[str, Query(description="The instance slug, typed to confirm")],
) -> None:
    await use_case(principal, instance, confirm)


@router.post("/{instance}/discover", summary="Read /info again (version, auth mode, isolation)")
async def discover_instance(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[Rediscover]
) -> ConnectedOut:
    found, diagnosis = await use_case(principal, instance)
    return ConnectedOut(
        instance=InstanceOut.from_domain(found),
        steps=[StepOut(id=s.id, label=s.label, status=s.status, detail=s.detail, hint=s.hint) for s in diagnosis.steps],
    )


@router.post("/{instance}/test", summary="Test connection: DNS, TLS, AgentOS, version, token, enforced scopes")
async def test_instance(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[TestConnection]
) -> TestReportOut:
    return TestReportOut.from_report(await use_case(principal, instance))


@router.get("/{instance}/keys/public", summary="Public keys, the config snippet and the JWKS location")
async def get_keys(instance: str, principal: FromDishka[Principal], use_case: FromDishka[GetKeys]) -> KeysOut:
    return KeysOut.from_view(await use_case(principal, instance))


@router.post("/{instance}/keys/rotate", summary="Rotate the key pair: stage a next key, then activate it")
async def rotate_keys(
    instance: str, body: RotateIn, principal: FromDishka[Principal], use_case: FromDishka[RotateKeys]
) -> KeysOut:
    return KeysOut.from_view(await use_case(principal, instance, body.action))


@router.post("/{instance}/keys/verify", summary="Verify a token against this instance's keys")
async def verify_token(
    instance: str, body: VerifyTokenIn, principal: FromDishka[Principal], use_case: FromDishka[VerifyToken]
) -> TokenCheckOut:
    return TokenCheckOut.from_check(await use_case(principal, instance, body.token))


@router.get("/{instance}/health", summary="Reachability, latency, version drift and capabilities")
async def get_health(instance: str, principal: FromDishka[Principal], use_case: FromDishka[GetHealth]) -> HealthOut:
    return HealthOut.from_view(await use_case(principal, instance))


@router.get("/{instance}/capabilities", summary="The capability matrix (07 §3)")
async def get_capabilities(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[GetHealth]
) -> list[CapabilityOut]:
    view = await use_case(principal, instance)
    return [CapabilityOut.from_domain(item) for item in view.capabilities]


@router.get("/{instance}/config", summary="The runtime's /config, as last fetched (needs config:read there)")
async def get_config(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetConfig],
    refresh: Annotated[bool, Query(description="Fetch it from the runtime now")] = False,
) -> ConfigOut:
    return ConfigOut.from_view(await use_case(principal, instance, refresh=refresh))


@well_known.get("/instances/{instance_id}/jwks.json", summary="Public keys of an instance (current and next), JWKS")
async def jwks(instance_id: str, use_case: FromDishka[Jwks]) -> dict[str, list[dict[str, str]]]:
    return await use_case(instance_id)
