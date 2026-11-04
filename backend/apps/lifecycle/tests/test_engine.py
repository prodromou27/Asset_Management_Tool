"""Pure matching and assessment rules (Task 015, ASM-53). No database."""

from datetime import date, timedelta

import pytest

from apps.lifecycle import assessment
from apps.lifecycle.assessment import Claim, evaluate, summarize
from apps.lifecycle.matching import Catalogue, Entry, key, match_hardware, match_os
from apps.lifecycle.models import Status

TODAY = date(2026, 11, 4)
T = [180, 90]


def claim(milestone_type, days, source="vendor", verification="verified", ident=None):
    return Claim(
        id=ident or f"{milestone_type}-{days}-{source}",
        milestone_type=milestone_type,
        date=TODAY + timedelta(days=days),
        source_type=source,
        verification=verification,
    )


# --- Assessment -------------------------------------------------------------------------------


def test_no_evidence_is_unknown_never_supported():
    result = evaluate([], TODAY, T)
    assert result.status == Status.UNKNOWN
    assert "No verified lifecycle dates" in result.reasons[0]


def test_pending_and_rejected_dates_do_not_count():
    claims = [
        claim("end_of_standard_support", -10, verification="pending"),
        claim("end_of_standard_support", -20, verification="rejected"),
    ]
    result = evaluate(claims, TODAY, T)
    assert result.status == Status.UNKNOWN
    assert "awaiting verification" in result.reasons[0]


def test_future_date_beyond_thresholds_is_announced():
    result = evaluate([claim("end_of_standard_support", 400)], TODAY, T)
    assert (result.status, result.days_remaining, result.support_level) == (
        Status.EOL_ANNOUNCED,
        400,
        "standard",
    )
    assert result.evidence_quality == "vendor" and result.threshold_days is None


@pytest.mark.parametrize(("days", "tier"), [(180, 180), (91, 180), (90, 90), (1, 90), (0, 90)])
def test_warning_thresholds(days, tier):
    result = evaluate([claim("end_of_standard_support", days)], TODAY, T)
    assert (result.status, result.threshold_days, result.days_remaining) == (
        Status.EXPIRING,
        tier,
        days,
    )


def test_milestone_date_is_the_last_supported_day():
    assert evaluate([claim("end_of_support", 0)], TODAY, T).status == Status.EXPIRING
    passed = evaluate([claim("end_of_support", -1)], TODAY, T)
    assert (passed.status, passed.days_remaining, passed.support_level) == (Status.EOS, -1, "ended")


def test_security_updates_ended_before_support_end():
    claims = [claim("end_of_security_updates", -30), claim("end_of_standard_support", 500)]
    result = evaluate(claims, TODAY, T)
    assert result.status == Status.SECURITY_MAINTENANCE_ENDED
    assert result.milestone_type == "end_of_security_updates"


def test_security_updates_ending_soon_is_expiring_even_if_support_is_far():
    claims = [claim("end_of_security_updates", 60), claim("end_of_standard_support", 900)]
    result = evaluate(claims, TODAY, T)
    assert (result.status, result.milestone_type, result.threshold_days) == (
        Status.EXPIRING,
        "end_of_security_updates",
        90,
    )


def test_extended_support_is_not_counted_by_default():
    claims = [claim("end_of_standard_support", -10), claim("end_of_extended_support", 700)]
    result = evaluate(claims, TODAY, T)
    assert result.status == Status.EOS
    assert result.support_level == "extended"
    assert any("Extended support is published" in r for r in result.reasons)


def test_extended_support_counts_when_configured():
    claims = [claim("end_of_standard_support", -10), claim("end_of_extended_support", 700)]
    result = evaluate(claims, TODAY, T, count_extended=True)
    assert (result.status, result.milestone_type, result.support_level) == (
        Status.EOL_ANNOUNCED,
        "end_of_extended_support",
        "extended",
    )


def test_final_end_of_support_governs_when_no_standard_date():
    result = evaluate([claim("end_of_sale", -300), claim("end_of_support", 120)], TODAY, T)
    assert (result.status, result.milestone_type) == (Status.EXPIRING, "end_of_support")


def test_end_of_sale_alone_is_never_supported():
    result = evaluate([claim("end_of_sale", -30)], TODAY, T)
    assert result.status == Status.EOL_ANNOUNCED
    assert "No verified end-of-support date" in result.reasons[0]
    assert result.threshold_days is None


def test_conflicting_vendor_dates_block_the_status():
    claims = [
        claim("end_of_standard_support", 100, ident="a"),
        claim("end_of_standard_support", 300, ident="b"),
    ]
    result = evaluate(claims, TODAY, T)
    assert result.status == Status.UNVERIFIED
    assert "Conflicting verified dates" in result.reasons[0]


def test_vendor_evidence_outranks_third_party():
    claims = [
        claim("end_of_standard_support", 400, source="vendor"),
        claim("end_of_standard_support", 30, source="third_party"),
    ]
    result = evaluate(claims, TODAY, T)
    assert (result.status, result.days_remaining, result.evidence_quality) == (
        Status.EOL_ANNOUNCED,
        400,
        "vendor",
    )
    assert any("lower-precedence source" in r for r in result.reasons)


def test_third_party_only_is_labelled():
    result = evaluate([claim("end_of_standard_support", -5, source="third_party")], TODAY, T)
    assert result.status == Status.EOS and result.evidence_quality == "third_party"
    assert any("third-party evidence only" in r for r in result.reasons)


def test_verified_vendor_statement_without_dates():
    supported = evaluate([], TODAY, T, statement="supported", statement_verified=True)
    assert supported.status == Status.SUPPORTED
    none = evaluate([], TODAY, T, statement="not_announced", statement_verified=True)
    assert none.status == Status.NOT_ANNOUNCED
    unverified = evaluate([], TODAY, T, statement="supported", statement_verified=False)
    assert unverified.status == Status.UNKNOWN


def test_dates_outrank_a_supported_statement():
    result = evaluate(
        [claim("end_of_standard_support", -1)],
        TODAY,
        T,
        statement="supported",
        statement_verified=True,
    )
    assert result.status == Status.EOS


@pytest.mark.parametrize(
    ("statuses", "summary"),
    [
        (["supported", "eos"], "eos"),
        (["eol_announced", "unknown"], "unknown"),
        (["supported", "unverified"], "unknown"),
        (["supported", "not_applicable"], "supported"),
        (["not_applicable", "not_applicable"], "unknown"),
        (["expiring", "security_maintenance_ended"], "security_maintenance_ended"),
    ],
)
def test_asset_summary_is_the_worst_applicable_dimension(statuses, summary):
    assert summarize(statuses) == summary


def test_summary_order_covers_every_asset_status():
    from apps.assets.models import Asset

    assert set(assessment.SUMMARY_ORDER) == set(Asset.SupportStatus.values)


# --- Matching ---------------------------------------------------------------------------------


def entry(ident, kind, vendor, name, release="", family="", aliases=()):
    return Entry(
        id=ident,
        kind=kind,
        vendor_key=key(vendor),
        name_key=key(name),
        release_key=key(release),
        family_key=key(family),
        label=f"{vendor} {name} {release}".strip(),
        aliases=[(k, key(v), key(r)) for k, v, r in aliases],
    )


@pytest.fixture
def cat():
    return Catalogue(
        vendor_aliases={"cisco systems": "Cisco"},
        vendors={"cisco", "microsoft", "fortinet"},
        entries=[
            entry(
                "c9300",
                "hardware",
                "Cisco",
                "C9300-48P",
                family="Catalyst 9300",
                aliases=[("part_number", "C9300-48P-E", "")],
            ),
            entry("c9200", "hardware", "Cisco", "C9200-24T"),
            entry("dup-a", "hardware", "Cisco", "WS-X1"),
            entry("dup-b", "hardware", "Cisco", "WS-X1-ALT", aliases=[("model", "WS-X1", "")]),
            entry("iosxe179", "firmware", "Cisco", "IOS XE", "17.9"),
            entry("iosxe1712", "firmware", "Cisco", "IOS XE", "17.12"),
            entry(
                "win10",
                "operating_system",
                "Microsoft",
                "Windows 10 Enterprise",
                "22H2",
                aliases=[("os_name", "Windows 10 Enterprise", "10.0.19045")],
            ),
            entry("fos72", "firmware", "Fortinet", "FortiOS", "7.2"),
            entry("fos72-b", "firmware", "Fortinet", "FortiOS Carrier", "7.2"),
        ],
    )


def test_exact_hardware_match_is_case_and_space_insensitive(cat):
    result = match_hardware(cat, "Cisco", " c9300-48p ", set())
    assert (result.state, result.method, result.product_id) == ("matched", "exact", "c9300")


def test_part_number_alias_and_vendor_alias(cat):
    result = match_hardware(cat, "Cisco Systems", "C9300-48P-E", set())
    assert (result.state, result.method, result.product_id) == ("matched", "alias", "c9300")


def test_unknown_manufacturer_and_missing_model(cat):
    assert match_hardware(cat, "Contoso", "X1", set()).state == "no_match"
    assert "not in the lifecycle catalogue" in match_hardware(cat, "Contoso", "X1", set()).reason
    assert match_hardware(cat, "Cisco", "", set()).reason == "Model not recorded."
    assert match_hardware(cat, "", "C9300-48P", set()).reason == "Manufacturer not recorded."


def test_ambiguous_model_is_never_selected_silently(cat):
    result = match_hardware(cat, "Cisco", "WS-X1", set())
    assert result.state == "candidate" and result.product_id is None
    assert {c["product_id"] for c in result.candidates} == {"dup-a", "dup-b"}


def test_revision_suffix_needs_review(cat):
    result = match_hardware(cat, "Cisco", "C9300-48P-A", set())
    assert result.state == "candidate"
    assert [c["product_id"] for c in result.candidates] == ["c9300"]


def test_family_name_alone_never_matches(cat):
    result = match_hardware(cat, "Cisco", "Catalyst 9300", set())
    assert result.state == "candidate" and result.product_id is None


def test_rejected_products_are_not_proposed_again(cat):
    assert match_hardware(cat, "Cisco", "C9300-48P-A", {"c9300"}).state == "no_match"
    result = match_hardware(cat, "Cisco", "WS-X1", {"dup-b"})
    assert (result.state, result.product_id) == ("matched", "dup-a")


def test_os_exact_release(cat):
    result = match_os(cat, "Cisco", "IOS XE", "17.12", "", set())
    assert (result.state, result.product_id) == ("matched", "iosxe1712")


def test_os_build_alias(cat):
    result = match_os(cat, "Dell", "Windows 10 Enterprise", "10.0.19045", "", set())
    assert (result.state, result.method, result.product_id) == ("matched", "alias", "win10")


def test_os_patch_release_needs_review_and_never_picks_a_sibling(cat):
    result = match_os(cat, "Cisco", "IOS XE", "17.9.4", "", set())
    assert result.state == "candidate"
    assert [c["product_id"] for c in result.candidates] == ["iosxe179"]  # not 17.12


def test_os_without_version_is_unknown(cat):
    result = match_os(cat, "Cisco", "IOS XE", "", "", set())
    assert result.state == "no_match" and "Version" in result.reason


def test_unknown_os_and_unknown_version(cat):
    assert match_os(cat, "Cisco", "NX-OS", "10.2", "", set()).state == "no_match"
    assert match_os(cat, "Cisco", "IOS XE", "16.3", "", set()).state == "no_match"


def test_firmware_version_only_is_always_reviewed(cat):
    result = match_os(cat, "Fortinet", "", "", "7.2", set())
    assert result.state == "candidate"
    assert {c["product_id"] for c in result.candidates} == {"fos72", "fos72-b"}


def test_nothing_recorded_for_os(cat):
    assert match_os(cat, "Cisco", "", "", "", set()).reason == (
        "No operating system or firmware version recorded."
    )


# --- Software matching (Task 016a) -----------------------------------------------------------


@pytest.fixture
def sw_cat():
    from apps.lifecycle.matching import Catalogue

    return Catalogue(
        vendor_aliases={"example software corporation": "Example Software Corp"},
        vendors={"example software corp"},
        entries=[
            entry(
                "office16",
                "software",
                "Example Software Corp",
                "Example Office Suite",
                "16.0",
                aliases=[("product_name", "Example Office Suite", "16.0.17928.20156")],
            ),
            entry("office19", "software", "Example Software Corp", "Example Office Suite", "19.0"),
        ],
    )


def test_software_exact_and_alias(sw_cat):
    from apps.lifecycle.matching import match_software

    exact = match_software(sw_cat, "Example Software Corp", "Example Office Suite", "19.0", set())
    assert (exact.state, exact.method, exact.product_id) == ("matched", "exact", "office19")
    build = match_software(
        sw_cat, "Example Software Corporation", "example office suite", "16.0.17928.20156", set()
    )
    assert (build.state, build.method, build.product_id) == ("matched", "alias", "office16")


def test_software_needs_review_without_publisher_or_exact_release(sw_cat):
    from apps.lifecycle.matching import match_software

    no_publisher = match_software(sw_cat, "", "Example Office Suite", "19.0", set())
    assert no_publisher.state == "candidate" and no_publisher.product_id is None
    patch = match_software(
        sw_cat, "Example Software Corp", "Example Office Suite", "16.0.99999.1", set()
    )
    assert [c["product_id"] for c in patch.candidates] == ["office16"]


def test_software_unknown_cases(sw_cat):
    from apps.lifecycle.matching import match_software

    assert (
        match_software(sw_cat, "Example Software Corp", "Other App", "1.0", set()).state
        == "no_match"
    )
    # An unknown publisher with a catalogued name is reviewed, never matched or dropped.
    assert (
        match_software(sw_cat, "Other Vendor", "Example Office Suite", "19.0", set()).state
        == "candidate"
    )
    assert (
        match_software(sw_cat, "Example Software Corp", "Example Office Suite", "", set()).state
        == "no_match"
    )
    assert (
        match_software(sw_cat, "Example Software Corp", "Example Office Suite", "20.0", set()).state
        == "no_match"
    )
