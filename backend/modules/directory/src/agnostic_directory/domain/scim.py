"""SCIM 2.0 protocol pieces that don't depend on storage.

Schemas, errors, list responses, discovery documents, pagination and attribute projection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from agnostic_directory.domain.scim_filter import get_key

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_SCHEMA = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SPC_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
MEDIA_TYPE = "application/scim+json"
DEFAULT_COUNT = 100
MAX_COUNT = 500
ALWAYS_RETURNED = frozenset({"id", "schemas", "meta"})

type Json = dict[str, object]


class ScimError(Exception):
    """An error answered in the SCIM error schema, e.g. 409 ``uniqueness`` or 400 ``invalidFilter``."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> Json:
        body: Json = {"schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            body["scimType"] = self.scim_type
        return body


@dataclass(frozen=True, slots=True)
class Page:
    start_index: int
    count: int

    @classmethod
    def of(cls, start_index: int | None, count: int | None) -> Page:
        """RFC 7644 §3.4.2.4: ``startIndex`` is 1-based (values below 1 mean 1), ``count`` is capped, 0 is allowed."""
        start = max(1, start_index or 1)
        size = DEFAULT_COUNT if count is None else max(0, min(count, MAX_COUNT))
        return cls(start_index=start, count=size)

    def slice[T](self, items: Sequence[T]) -> list[T]:
        return list(items[self.start_index - 1 : self.start_index - 1 + self.count])


def list_response(resources: Sequence[Json], *, total: int, page: Page) -> Json:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": page.start_index,
        "itemsPerPage": len(resources),
        "Resources": list(resources),
    }


def project(resource: Json, *, attributes: str | None, excluded: str | None) -> Json:
    """``attributes=userName,emails`` keeps those (plus id, schemas, meta); ``excludedAttributes=members`` drops."""
    if attributes:
        wanted = {name.strip().rpartition(":")[2].split(".", 1)[0].lower() for name in attributes.split(",")}
        return {key: value for key, value in resource.items() if key.lower() in wanted | ALWAYS_RETURNED}
    if excluded:
        dropped = {name.strip().rpartition(":")[2].split(".", 1)[0].lower() for name in excluded.split(",")}
        return {key: value for key, value in resource.items() if key.lower() not in dropped - ALWAYS_RETURNED}
    return resource


def put_attr(resource: Json, name: str, value: object) -> None:
    """Set ``name`` replacing any differently-cased key (IdPs send ``username`` as often as ``userName``)."""
    key = get_key(resource, name)
    if key is not None and key != name:
        del resource[key]
    if value is None:
        _ = resource.pop(name, None)
    else:
        resource[name] = value


def get_attr(resource: Mapping[str, object], name: str) -> object:
    key = get_key(resource, name)
    return resource[key] if key is not None else None


def get_str(resource: Mapping[str, object], name: str) -> str | None:
    value = get_attr(resource, name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def primary_email(resource: Mapping[str, object]) -> str | None:
    """The primary email, else the work email, else the first one."""
    emails = get_attr(resource, "emails")
    if not isinstance(emails, list):
        return None
    entries = [cast("Mapping[str, object]", e) for e in cast("list[object]", emails) if isinstance(e, Mapping)]
    entries = [entry for entry in entries if get_str(entry, "value")]
    primary = [entry for entry in entries if get_attr(entry, "primary") in (True, "true", "True")]
    work = [entry for entry in entries if str(get_attr(entry, "type") or "").lower() == "work"]
    for entry in (*primary, *work, *entries):
        return get_str(entry, "value")
    return None


def display_name_of(resource: Mapping[str, object]) -> str | None:
    if name := get_str(resource, "displayName"):
        return name
    name_value = get_attr(resource, "name")
    if isinstance(name_value, Mapping):
        parts = cast("Mapping[str, object]", name_value)
        if formatted := get_str(parts, "formatted"):
            return formatted
        joined = " ".join(p for p in (get_str(parts, "givenName"), get_str(parts, "familyName")) if p)
        if joined:
            return joined
    return None


def member_ids(resource: Mapping[str, object]) -> list[str]:
    """The ``value`` of each element of ``members``, in order, without duplicates."""
    members = get_attr(resource, "members")
    if not isinstance(members, list):
        return []
    values: list[str] = []
    for member in cast("list[object]", members):
        if isinstance(member, Mapping):
            value = get_str(cast("Mapping[str, object]", member), "value")
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def service_provider_config(base_url: str) -> Json:
    return {
        "schemas": [SPC_SCHEMA],
        "documentationUri": "https://docs.agnostic.dev/admin/directory-sync",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_COUNT},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer token",
                "description": "A SCIM token created in Org settings > Directory sync",
                "primary": True,
            }
        ],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base_url}/ServiceProviderConfig"},
    }


def resource_types(base_url: str) -> list[Json]:
    return [
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "description": "People in the org",
            "schema": USER_SCHEMA,
            "schemaExtensions": [{"schema": ENTERPRISE_SCHEMA, "required": False}],
            "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/User"},
        },
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "description": "Groups whose members share role bindings",
            "schema": GROUP_SCHEMA,
            "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/Group"},
        },
    ]


def _attribute(
    name: str,
    kind: str = "string",
    *,
    multi: bool = False,
    required: bool = False,
    unique: str = "none",
    mutability: str = "readWrite",
    returned: str = "default",
    case_exact: bool = False,
    sub: list[Json] | None = None,
) -> Json:
    attribute: Json = {
        "name": name,
        "type": kind,
        "multiValued": multi,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": returned,
        "uniqueness": unique,
    }
    if sub is not None:
        attribute["subAttributes"] = sub
    return attribute


def schemas(base_url: str) -> list[Json]:
    multi_value = [_attribute("value"), _attribute("type"), _attribute("primary", "boolean"), _attribute("display")]
    user: Json = {
        "schemas": [SCHEMA_SCHEMA],
        "id": USER_SCHEMA,
        "name": "User",
        "description": "User account",
        "attributes": [
            _attribute("userName", required=True, unique="server"),
            _attribute(
                "name",
                "complex",
                sub=[_attribute(n) for n in ("formatted", "familyName", "givenName", "middleName")],
            ),
            _attribute("displayName"),
            _attribute("emails", "complex", multi=True, sub=multi_value),
            _attribute("active", "boolean"),
            _attribute(
                "groups",
                "complex",
                multi=True,
                mutability="readOnly",
                sub=[_attribute("value", mutability="readOnly"), _attribute("display", mutability="readOnly")],
            ),
        ],
        "meta": {"resourceType": "Schema", "location": f"{base_url}/Schemas/{USER_SCHEMA}"},
    }
    group: Json = {
        "schemas": [SCHEMA_SCHEMA],
        "id": GROUP_SCHEMA,
        "name": "Group",
        "description": "Group",
        "attributes": [
            _attribute("displayName", required=True),
            _attribute(
                "members",
                "complex",
                multi=True,
                sub=[_attribute("value", mutability="immutable"), _attribute("display", mutability="immutable")],
            ),
        ],
        "meta": {"resourceType": "Schema", "location": f"{base_url}/Schemas/{GROUP_SCHEMA}"},
    }
    enterprise: Json = {
        "schemas": [SCHEMA_SCHEMA],
        "id": ENTERPRISE_SCHEMA,
        "name": "EnterpriseUser",
        "description": "Enterprise user (kept as sent; not used for access)",
        "attributes": [_attribute(n) for n in ("employeeNumber", "department", "organization", "division")],
        "meta": {"resourceType": "Schema", "location": f"{base_url}/Schemas/{ENTERPRISE_SCHEMA}"},
    }
    return [user, group, enterprise]
