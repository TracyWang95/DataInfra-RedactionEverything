"""HaS Image 21 类 slug / class_id 映射（发布前契约测试）。"""
from app.core.has_image_categories import (
    CLASS_ID_TO_SLUG,
    HAS_IMAGE_CATEGORIES,
    SLUG_TO_CLASS_ID,
    SLUG_TO_NAME_ZH,
    class_index_to_slug,
    preset_type_color,
    slug_list_to_class_indices,
)


def test_has_image_twenty_one_categories_sequential_ids():
    assert len(HAS_IMAGE_CATEGORIES) == 21
    ids = [c.class_id for c in HAS_IMAGE_CATEGORIES]
    assert ids == list(range(21))
    slugs = [c.id for c in HAS_IMAGE_CATEGORIES]
    assert len(set(slugs)) == 21


def test_slug_bidirectional_mapping():
    assert SLUG_TO_CLASS_ID["face"] == 0
    assert SLUG_TO_CLASS_ID["paper"] == 20
    assert CLASS_ID_TO_SLUG[0] == "face"
    assert CLASS_ID_TO_SLUG[20] == "paper"
    assert len(SLUG_TO_CLASS_ID) == 21
    assert len(CLASS_ID_TO_SLUG) == 21


def test_slug_list_to_class_indices_none_means_unfiltered():
    assert slug_list_to_class_indices(None) is None


def test_slug_list_to_class_indices_empty_list_means_no_classes():
    assert slug_list_to_class_indices([]) == []


def test_slug_list_to_class_indices_invalid_only_returns_empty():
    assert slug_list_to_class_indices(["not_a_real_category", "xyz"]) == []


def test_slug_list_to_class_indices_mixed_filters_unknown():
    assert slug_list_to_class_indices(["face", "bad_slug", "qr_code"]) == [0, 18]


def test_class_index_to_slug_unknown():
    assert class_index_to_slug(999) == "class_999"


def test_preset_type_color_stable():
    assert preset_type_color(0) == preset_type_color(0)
    assert preset_type_color(0) != preset_type_color(1)


def test_chinese_names_present_for_core_slugs():
    assert SLUG_TO_NAME_ZH["official_seal"] == "公章"
    assert SLUG_TO_NAME_ZH["id_card"] == "身份证"
