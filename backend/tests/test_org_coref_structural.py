"""ORG alias coreference via pure subsequence coverage — no enumerated suffix /
region / generic-word lists.

An organisation's short form is an in-order subsequence of its full registered
name ("深圳译科技公司" ⊂ "深圳译科技有限公司"), so high subsequence COVERAGE of the
shorter name inside the longer one links them. A differing core ("第一" vs "第二")
or a different institution kind (医院 vs 保险公司) drops coverage below the bar, so
unrelated orgs never link — the structural signal replaces the word tables.
"""
from app.services.hybrid_ner_service import HybridNERService as H


def _related(short: str, long: str) -> bool:
    return H._org_names_look_related(
        H._compact_org_name(short), H._compact_org_name(long)
    )


# --- should link: same org, short form is a subsequence of the full name ---

def test_registered_suffix_variant_links():
    assert _related("深圳译科技公司", "深圳译科技有限公司")


def test_dropped_registered_boilerplate_links():
    assert _related("深圳译科技", "深圳译科技有限公司")


def test_full_short_name_inside_longer_links():
    assert _related("云南呈祥律师事务所", "云南呈祥律师事务所昆明分所")


# --- should NOT link: different orgs that merely share a fragment ---

def test_cross_kind_same_prefix_does_not_link():
    # 医院 vs 保险公司 — shared "深圳译" is far below full coverage of the alias.
    assert not _related("深圳译医院", "深圳译保险有限公司")


def test_different_core_does_not_link():
    assert not _related("深圳市第一医院", "深圳市第二医院集团")


def test_shared_region_and_suffix_only_does_not_link():
    # Only 北京…公司 overlap; the distinctive core (保险 vs 科技) breaks coverage.
    assert not _related("北京保险有限公司", "北京科技发展有限公司")


# --- guards ---

def test_too_short_alias_does_not_link():
    # A 2-char fragment is not enough evidence of the same organisation.
    assert not _related("深圳", "深圳译科技有限公司")
