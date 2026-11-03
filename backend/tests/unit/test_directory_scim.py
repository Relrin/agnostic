"""SCIM filters and PATCH as Okta and Entra ID send them, plus the pure pieces of directory sync."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agnostic_directory.domain.scim import Page, ScimError, display_name_of, member_ids, primary_email, project
from agnostic_directory.domain.scim_filter import (
    And,
    AttrPath,
    Compare,
    Not,
    Or,
    Present,
    ScimFilterError,
    ValuePath,
    coerce_bool,
    equality,
    matches,
    parse_attr_path,
    parse_filter,
    parse_patch_path,
)
from agnostic_directory.domain.scim_patch import ScimPatchError, apply_patch, parse_operations
from agnostic_directory.domain.sync import MappingRule, ScimToken, group_selected

ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"

BARBARA: dict[str, Any] = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User", ENTERPRISE],
    "id": "usr_01J",
    "externalId": "00u1abcd",
    "userName": "Barbara.Jensen@Localhost.company",
    "name": {"givenName": "Barbara", "familyName": "Jensen"},
    "displayName": "Barbara Jensen",
    "emails": [
        {"value": "barbara@home.test", "type": "home"},
        {"value": "barbara.jensen@localhost.company", "type": "work", "primary": True},
    ],
    "active": True,
    "meta": {"lastModified": "2026-10-01T10:00:00Z"},
    ENTERPRISE: {"employeeNumber": "701984", "department": "Support"},
}


# --- filters ---------------------------------------------------------------------------------------------------


def test_okta_and_entra_lookups_parse() -> None:
    assert parse_filter('userName eq "barbara.jensen@localhost.company"') == Compare(
        AttrPath("userName"), "eq", "barbara.jensen@localhost.company"
    )
    assert parse_filter('externalId eq "00u1abcd"') == Compare(AttrPath("externalId"), "eq", "00u1abcd")
    assert parse_filter('displayName eq "support-ai"') == Compare(AttrPath("displayName"), "eq", "support-ai")


def test_precedence_parentheses_and_not() -> None:
    parsed = parse_filter('userName sw "b" or title pr and not (active eq false)')
    assert parsed == Or(
        Compare(AttrPath("userName"), "sw", "b"),
        And(Present(AttrPath("title")), Not(Compare(AttrPath("active"), "eq", value=False))),
    )
    grouped = parse_filter('(userName sw "b" or title pr) and active eq true')
    assert isinstance(grouped, And)
    assert isinstance(grouped.left, Or)


def test_value_paths_sub_attributes_and_schema_urns() -> None:
    assert parse_filter('emails[type eq "work" and value co "@localhost"]') == ValuePath(
        AttrPath("emails"),
        And(Compare(AttrPath("type"), "eq", "work"), Compare(AttrPath("value"), "co", "@localhost")),
    )
    trailing = parse_filter('emails[type eq "work"].value eq "barbara.jensen@localhost.company"')
    assert isinstance(trailing, ValuePath)
    assert parse_attr_path(f"{ENTERPRISE}:employeeNumber") == AttrPath("employeeNumber", schema=ENTERPRISE)
    assert parse_attr_path("urn:ietf:params:scim:schemas:core:2.0:User:name.givenName") == AttrPath(
        "name", sub="givenName"
    )
    assert parse_filter('meta.lastModified gt "2026-01-01T00:00:00Z"') == Compare(
        AttrPath("meta", sub="lastModified"), "gt", "2026-01-01T00:00:00Z"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('userName eq "barbara.jensen@localhost.company"', True),
        ('USERNAME EQ "BARBARA.JENSEN@LOCALHOST.COMPANY"', True),
        ('userName ne "someone@else.test"', True),
        ('userName co "jensen"', True),
        ('userName sw "barbara"', True),
        ('userName ew "@localhost.company"', True),
        ('externalId eq "00U1ABCD"', False),  # caseExact
        ('externalId eq "00u1abcd"', True),
        ('emails[type eq "work"].value eq "barbara.jensen@localhost.company"', True),
        ('emails[type eq "home" and value co "localhost"]', False),
        ('emails.value eq "barbara@home.test"', True),
        ('emails co "home.test"', True),
        ('name.givenName eq "Barbara"', True),
        ("title pr", False),
        ("name pr", True),
        ("active eq true", True),
        ("not (active eq true)", False),
        (f'{ENTERPRISE}:department eq "support"', True),
        ('meta.lastModified gt "2026-09-30T00:00:00Z"', True),
        ('meta.lastModified lt "2026-09-30T00:00:00Z"', False),
        (f"{ENTERPRISE}:employeeNumber ge 700000", True),
        ('displayName eq "Nobody" or userName sw "barbara"', True),
    ],
)
def test_filters_match_a_user(text: str, expected: bool) -> None:
    assert matches(parse_filter(text), BARBARA) is expected


def test_group_members_filter() -> None:
    group = {"displayName": "support-ai", "members": [{"value": "usr_1"}, {"value": "usr_2"}]}
    assert matches(parse_filter('members[value eq "usr_2"]'), group)
    assert matches(parse_filter('members.value eq "usr_1"'), group)
    assert not matches(parse_filter('members[value eq "usr_3"]'), group)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "userName",
        "userName eq",
        'userName zz "x"',
        '(userName eq "x"',
        'userName eq "x" junk',
        'emails[type eq "w"',
    ],
)
def test_bad_filters_are_rejected(text: str) -> None:
    with pytest.raises(ScimFilterError):
        _ = parse_filter(text)


def test_equality_index_lookups() -> None:
    assert equality(parse_filter('userName eq "A@B.test"')) == ("username", "A@B.test")
    assert equality(parse_filter('externalId eq "x"')) == ("externalid", "x")
    assert equality(parse_filter('emails[type eq "work"].value eq "a@b.test"')) == ("emails.value", "a@b.test")
    assert equality(parse_filter('userName co "x"')) is None


def test_patch_paths() -> None:
    path = parse_patch_path('members[value eq "usr_1"]')
    assert path.attr == AttrPath("members")
    assert path.filter == Compare(AttrPath("value"), "eq", "usr_1")
    assert path.sub is None
    path = parse_patch_path('emails[type eq "work"].value')
    assert path.sub == "value"
    with pytest.raises(ScimFilterError):
        _ = parse_patch_path('emails[type eq "work"')


def test_string_booleans() -> None:
    assert coerce_bool("False") is False
    assert coerce_bool("true") is True
    assert coerce_bool(value=True) is True
    assert coerce_bool("maybe") is None


# --- PATCH -----------------------------------------------------------------------------------------------------


def patch(resource: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    patched: dict[str, Any] = apply_patch(resource, parse_operations(body))
    return patched


def ops(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": list(operations)}


def test_okta_deactivates_without_a_path() -> None:
    patched = patch(BARBARA, (ops({"op": "replace", "value": {"active": False}})))
    assert patched["active"] is False
    assert BARBARA["active"] is True  # untouched


def test_entra_replace_with_capitalized_op_and_string_boolean() -> None:
    patched = patch(BARBARA, (ops({"op": "Replace", "path": "active", "value": "False"})))
    assert coerce_bool(patched["active"]) is False


def test_entra_value_object_with_dotted_and_urn_keys() -> None:
    patched = patch(
        BARBARA,
        (
            ops(
                {
                    "op": "Replace",
                    "value": {
                        "name.givenName": "Babs",
                        "displayName": "Babs Jensen",
                        f"{ENTERPRISE}:department": "Escalations",
                    },
                }
            )
        ),
    )
    assert patched["name"] == {"givenName": "Babs", "familyName": "Jensen"}
    assert patched["displayName"] == "Babs Jensen"
    assert patched[ENTERPRISE]["department"] == "Escalations"
    assert patched[ENTERPRISE]["employeeNumber"] == "701984"


def test_extension_object_without_a_path() -> None:
    patched = patch(
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"]},
        (ops({"op": "add", "value": {ENTERPRISE: {"department": "Support"}}})),
    )
    assert patched[ENTERPRISE] == {"department": "Support"}
    assert ENTERPRISE in patched["schemas"]


def test_filtered_paths_update_matching_elements() -> None:
    patched = patch(
        BARBARA,
        (ops({"op": "replace", "path": 'emails[type eq "work"].value', "value": "babs@localhost.company"})),
    )
    assert [e["value"] for e in patched["emails"]] == ["barbara@home.test", "babs@localhost.company"]


def test_entra_adds_a_work_email_through_a_filter_that_matches_nothing() -> None:
    patched = patch(
        {"userName": "x"},
        (ops({"op": "Add", "path": 'emails[type eq "work"].value', "value": "x@localhost.company"})),
    )
    assert patched["emails"] == [{"type": "work", "value": "x@localhost.company"}]


def test_sub_attribute_paths_and_removal() -> None:
    patched = patch(
        BARBARA,
        (
            ops(
                {"op": "replace", "path": "name.familyName", "value": "Jensen-Smith"},
                {"op": "remove", "path": 'emails[type eq "home"]'},
                {"op": "remove", "path": f"{ENTERPRISE}:employeeNumber"},
            )
        ),
    )
    assert patched["name"]["familyName"] == "Jensen-Smith"
    assert [e["type"] for e in patched["emails"]] == ["work"]
    assert "employeeNumber" not in patched[ENTERPRISE]


def test_group_member_operations() -> None:
    group = {"displayName": "support-ai", "members": [{"value": "usr_1"}, {"value": "usr_2"}]}
    # Okta: add members, remove one by filter.
    patched = patch(
        group,
        (
            ops(
                {"op": "add", "path": "members", "value": [{"value": "usr_3", "display": "C"}, {"value": "usr_1"}]},
                {"op": "remove", "path": 'members[value eq "usr_2"]'},
            )
        ),
    )
    assert member_ids(patched) == ["usr_1", "usr_3"]
    # Entra: remove with a value list, replace the display name in a value object.
    patched = patch(
        patched,
        (
            ops(
                {"op": "Remove", "path": "members", "value": [{"value": "usr_1"}]},
                {"op": "Replace", "value": {"id": "grp_x", "displayName": "Support AI"}},
            )
        ),
    )
    assert member_ids(patched) == ["usr_3"]
    assert patched["displayName"] == "Support AI"
    # Removing the attribute without a value clears it.
    assert member_ids(patch(patched, (ops({"op": "remove", "path": "members"})))) == []


@pytest.mark.parametrize(
    ("body", "scim_type"),
    [
        ({"Operations": []}, "invalidSyntax"),
        (ops({"op": "move", "path": "x"}), "invalidSyntax"),
        (ops({"op": "remove"}), "noTarget"),
        (ops({"op": "replace", "value": "x"}), "invalidValue"),
        (ops({"op": "replace", "path": 'emails[type eq "work"', "value": "x"}), "invalidPath"),
        (ops({"op": "replace", "path": 'emails[type co "w"].value', "value": "x"}), "noTarget"),
    ],
)
def test_bad_patches(body: dict[str, Any], scim_type: str) -> None:
    with pytest.raises(ScimPatchError) as raised:
        _ = patch({"emails": []}, (body))
    assert raised.value.scim_type == scim_type


# --- resources, pages, projection ------------------------------------------------------------------------------


def test_resource_helpers() -> None:
    assert primary_email(BARBARA) == "barbara.jensen@localhost.company"
    assert primary_email({"emails": [{"value": "a@x.test"}, {"value": "b@x.test", "type": "work"}]}) == "b@x.test"
    assert display_name_of({"name": {"givenName": "Ann", "familyName": "Lee"}}) == "Ann Lee"
    assert display_name_of({"displayName": " Ann "}) == "Ann"


def test_pages_and_projection() -> None:
    assert Page.of(None, None) == Page(1, 100)
    assert Page.of(0, 10_000) == Page(1, 500)
    assert Page.of(3, 2).slice([1, 2, 3, 4, 5]) == [3, 4]
    assert Page.of(1, 0).slice([1, 2]) == []
    assert set(project(BARBARA, attributes="userName", excluded=None)) == {"schemas", "id", "meta", "userName"}
    assert "members" not in project({"id": "g", "members": []}, attributes=None, excluded="members")
    assert ScimError(409, "taken", "uniqueness").body() == {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": "409",
        "detail": "taken",
        "scimType": "uniqueness",
    }


# --- sync ------------------------------------------------------------------------------------------------------


def test_mapping_rules_match_by_name_or_id() -> None:
    now = datetime.now(UTC)
    rule = MappingRule("dmr_1", "scim", None, "Support-AI", "grp_manual", "usr_1", now)
    assert rule.matches("scim", "00g1", "support-ai")
    assert rule.matches("scim", "Support-AI", None)
    assert not rule.matches("google_directory", "00g1", "support-ai")
    claim = MappingRule("dmr_2", "oidc_claim", "corp", "support", "grp_manual", "usr_1", now)
    assert claim.matches("oidc_claim", "corp:support", "support")
    assert not claim.matches("oidc_claim", "github:support", "support")


def test_google_group_filter() -> None:
    assert group_selected((), email="anything@x.test", name="Anything")
    assert group_selected(("eng-*",), email="eng-platform@x.test", name="Platform")
    assert not group_selected(("eng-*",), email="sales@x.test", name="Engineering fans")
    assert group_selected(("support",), email="tier2@x.test", name="Support Tier 2")


def test_token_states() -> None:
    now = datetime.now(UTC)
    token = ScimToken("scim_1", "Okta SCIM", "agn_scim_abcd", "h", "usr_1", now, None, None, None, None)
    assert token.state(now) == "active"
    rotating = ScimToken("scim_1", "Okta SCIM", "p", "h", "usr_1", now, None, now + timedelta(hours=1), None, None)
    assert rotating.state(now) == "rotating"
    assert rotating.state(now + timedelta(hours=2)) == "expired"
    assert not rotating.usable(now + timedelta(hours=2))
