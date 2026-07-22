"""P0 bugs from the 2026-07-12 full-repo audit (real defects, not magic rules)."""

from app.services.entity_type_service import is_default_generic_entity_type_id
from app.services.structured_common import is_number_like
from app.services.structured_masking import bucket_value, generalize_value


def test_date_generalize_does_not_crash_and_extracts_year_month() -> None:
    # regex char class was GBK-corrupted (骞碷 = 年]) -> re.error at runtime
    assert generalize_value("2024-05-14", entity_type="DATE") == "2024-05"
    assert generalize_value("2024/5/1", entity_type="DATE") == "2024-05"
    assert generalize_value("2024年5月", entity_type="DATE") == "2024-05"
    # non-date text must not raise
    assert generalize_value("不是日期", entity_type="DATE") == "***"


def test_amount_bucket_strips_yen_symbol() -> None:
    # replace target was GBK-corrupted (楼 = ¥) -> ¥ amounts failed to parse
    assert bucket_value("¥1,000") != "***"
    assert bucket_value("￥2000") != "***"


def test_numeric_like_strips_currency_symbol() -> None:
    assert is_number_like("¥1,234.50") is True
    assert is_number_like("￥100") is True


def test_default_generic_guard_excludes_custom_types() -> None:
    # guard was always-true for custom ids (canonical upper-cased before the
    # lowercase startswith check) -> custom types leaked into default schema
    assert is_default_generic_entity_type_id("PERSON") is True
    assert is_default_generic_entity_type_id("custom_extension_jchk") is False
    assert is_default_generic_entity_type_id("CUSTOM_EXTENSION_JCHK") is False
