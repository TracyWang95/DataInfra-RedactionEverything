import json
import unittest
from pathlib import Path

from app.models.schemas import Entity
from app.models.type_mapping import canonical_type_id, id_to_cn, linkage_groups_for_type
from app.services.entity_type_service import (
    PRESET_ENTITY_TYPES,
    EntityTypeConfig,
    build_tag_template,
    get_default_generic_types,
    get_text_taxonomy,
    infer_linkage_groups,
    normalize_custom_entity_type,
)
from app.services.has_service import HaSService
from app.services.hybrid_ner_service import HybridNERService, _HaSChunk
from app.services.preset_service import _load_builtin_presets


class CustomEntityTaxonomyTests(unittest.TestCase):
    def test_linkage_groups_are_inferred_from_l1_l2(self):
        self.assertEqual(
            infer_linkage_groups("pii", "GEN_NUMBER_CODE"),
            ["identifier_like", "person_like"],
        )
        self.assertEqual(
            infer_linkage_groups("organization_subject", "GEN_NAME"),
            ["organization_like"],
        )
        self.assertEqual(
            infer_linkage_groups("pii", "GEN_NAME"),
            ["person_like"],
        )

    def test_custom_type_keeps_recognition_config_and_is_tagged_from_l3_name(self):
        custom = EntityTypeConfig(
            id="custom_supplier_doc_no",
            name="文书编号",
            data_domain="document_record",
            generic_target="GEN_NUMBER_CODE",
            regex_pattern=r"\d+",
            use_llm=False,
            coref_enabled=True,
            tag_template=None,
        )

        normalized = normalize_custom_entity_type(custom)

        # Recognition config (regex / use_llm) is preserved as configured;
        # taxonomy-derived fields are normalized.
        self.assertEqual(normalized.regex_pattern, r"\d+")
        self.assertFalse(normalized.use_llm)
        self.assertEqual(normalized.linkage_groups, ["identifier_like"])
        self.assertEqual(normalized.tag_template, "<文书编号[{index}]>")

    def test_tag_template_defaults_to_l3_label(self):
        self.assertEqual(build_tag_template("出生日期"), "<出生日期[{index}]>")

    def test_l3_atoms_birth_date_and_document_number_exist_but_defaults_stay_narrow(self):
        default_ids = {item.id for item in get_default_generic_types()}

        self.assertIn("ADDRESS", default_ids)
        # BIRTH_DATE / DOCUMENT_NUMBER remain first-class L3 atoms but are
        # opt-in: the default generic schema was narrowed to the core 9 types.
        self.assertNotIn("BIRTH_DATE", default_ids)
        self.assertNotIn("DOCUMENT_NUMBER", default_ids)
        self.assertTrue(PRESET_ENTITY_TYPES["BIRTH_DATE"].enabled)
        self.assertTrue(PRESET_ENTITY_TYPES["DOCUMENT_NUMBER"].enabled)
        # Alias/cn_terms translation layer is deleted: ids normalize by pure
        # string hygiene only, LEGAL_CASE_ID is its own first-class item now.
        self.assertEqual(canonical_type_id("LEGAL_CASE_ID"), "LEGAL_CASE_ID")
        self.assertEqual(id_to_cn("ADDRESS"), "地址")
        self.assertEqual(id_to_cn("BIRTH_DATE"), "出生日期")
        self.assertEqual(id_to_cn("DOCUMENT_NUMBER"), "文书编号")
        self.assertEqual(linkage_groups_for_type("BIRTH_DATE"), {"date_like", "person_like"})
        self.assertEqual(linkage_groups_for_type("DOCUMENT_NUMBER"), {"identifier_like"})

    def test_l1_domains_do_not_use_l2_concepts(self):
        domains = {item.data_domain for item in PRESET_ENTITY_TYPES.values()}
        self.assertNotIn("identifier_code", domains)
        self.assertNotIn("sensitive_attribute", domains)

        birth_date = PRESET_ENTITY_TYPES["BIRTH_DATE"]
        age = PRESET_ENTITY_TYPES["AGE"]
        document_number = PRESET_ENTITY_TYPES["DOCUMENT_NUMBER"]

        self.assertEqual((birth_date.data_domain, birth_date.generic_target), ("pii", "GEN_DATE_TIME"))
        self.assertEqual((age.data_domain, age.generic_target), ("pii", "GEN_ATTRIBUTE_STATUS"))
        self.assertEqual(
            (document_number.data_domain, document_number.generic_target),
            ("document_record", "GEN_NUMBER_CODE"),
        )

    def test_text_taxonomy_contract_is_complete_and_deduplicated(self):
        taxonomy = get_text_taxonomy()
        domains = taxonomy.domains
        domain_ids = [domain.value for domain in domains]

        self.assertEqual(len(domain_ids), len(set(domain_ids)))
        self.assertNotIn("identifier_code", domain_ids)
        self.assertNotIn("sensitive_attribute", domain_ids)

        for domain in domains:
            target_ids = [target.value for target in domain.targets]
            self.assertTrue(domain.label)
            self.assertIn(domain.default_target, target_ids)
            self.assertEqual(len(target_ids), len(set(target_ids)))
            self.assertTrue(all(target.label for target in domain.targets))

        pii = next(domain for domain in domains if domain.value == "pii")
        self.assertIn("GEN_NUMBER_CODE", [target.value for target in pii.targets])
        self.assertIn("GEN_DATE_TIME", [target.value for target in pii.targets])

    def test_text_config_files_do_not_reintroduce_retired_l1_domains(self):
        root = Path(__file__).resolve().parents[2]
        forbidden_l1 = {"identifier_code", "sensitive_attribute"}
        text_paths = [
            root / "backend" / "config" / "preset_entity_types.json",
            root / "backend" / "data" / "entity_types.json",
        ]

        for path in text_paths:
            if "data" in path.parts and not path.exists():
                continue  # runtime snapshot, absent in CI / fresh checkouts
            data = json.loads(path.read_text(encoding="utf-8"))
            domains = {item.get("data_domain") for item in data.values()}
            self.assertFalse(domains & forbidden_l1, f"{path} contains retired L1 domains")

        pipeline_paths = [
            root / "backend" / "config" / "preset_pipeline_types.json",
            root / "backend" / "data" / "pipelines.json",
        ]
        for path in pipeline_paths:
            if "data" in path.parts and not path.exists():
                continue  # runtime snapshot, absent in CI / fresh checkouts
            data = json.loads(path.read_text(encoding="utf-8"))
            ocr_has_types = data["ocr_has"] if isinstance(data["ocr_has"], list) else data["ocr_has"]["types"]
            domains = {item.get("data_domain") for item in ocr_has_types}
            self.assertNotIn("visual_mark", domains, f"{path} mixes visual feature taxonomy into text")
            self.assertFalse(domains & forbidden_l1, f"{path} contains retired L1 domains")

    def test_birth_date_wins_same_span_dedup_over_date_and_age(self):
        text = "1985年7月15日出生"
        service = HybridNERService()
        entities = [
            Entity(id="date", text="1985年7月15日", type="DATE", start=0, end=10, confidence=0.95, source="has"),
            Entity(id="age", text="1985年7月15日", type="AGE", start=0, end=10, confidence=0.95, source="has"),
            Entity(id="birth", text="1985年7月15日", type="BIRTH_DATE", start=0, end=10, confidence=0.95, source="has"),
        ]

        result = service._cross_validate(
            entities,
            text,
            {"DATE", "AGE", "BIRTH_DATE"},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].type, "BIRTH_DATE")

    def test_entity_edge_punctuation_is_not_consumed(self):
        text = "住广东省深圳市南山区科技园。"
        service = HybridNERService()
        entities = [
            Entity(
                id="address",
                text="广东省深圳市南山区科技园。",
                type="ADDRESS",
                start=1,
                end=len(text),
                confidence=0.95,
                source="has",
            ),
        ]

        result = service._cross_validate(entities, text, {"ADDRESS"})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "广东省深圳市南山区科技园")
        self.assertEqual(result[0].start, 1)
        self.assertEqual(result[0].end, len(text) - 1)

    def test_birth_date_wins_overlapping_age_phrase(self):
        text = "1985年7月15日出生"
        service = HybridNERService()
        entities = [
            Entity(id="birth", text="1985年7月15日", type="BIRTH_DATE", start=0, end=10, confidence=0.95, source="has"),
            Entity(id="age", text="1985年7月15日出生", type="AGE", start=0, end=12, confidence=0.95, source="has"),
        ]

        result = service._cross_validate(entities, text, {"BIRTH_DATE", "AGE"})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].type, "BIRTH_DATE")
        self.assertEqual(result[0].text, "1985年7月15日")

    def test_same_span_person_attribute_conflicts_keep_atom_l3(self):
        text = "女，汉族"
        service = HybridNERService()
        entities = [
            Entity(id="marital", text="女", type="MARITAL_STATUS", start=0, end=1, confidence=0.95, source="has"),
            Entity(id="gender", text="女", type="GENDER", start=0, end=1, confidence=0.95, source="has"),
            Entity(id="nation", text="汉族", type="NATIONALITY", start=2, end=4, confidence=0.95, source="has"),
            Entity(id="ethnicity", text="汉族", type="ETHNICITY", start=2, end=4, confidence=0.95, source="has"),
        ]

        result = service._cross_validate(
            entities,
            text,
            {"MARITAL_STATUS", "GENDER", "NATIONALITY", "ETHNICITY"},
        )

        self.assertEqual([(item.type, item.text) for item in result], [("GENDER", "女"), ("ETHNICITY", "汉族")])

    def test_chunk_relocation_uses_local_offsets_for_repeated_short_text(self):
        service = HybridNERService()
        full_text = "原告：张三，汉族。\n被告：李四，汉族。"
        chunk = _HaSChunk(text=full_text, line_offsets=(0, full_text.index("被告")))
        entities = [
            Entity(id="first", text="汉族", type="ETHNICITY", start=6, end=8, confidence=0.95, source="has"),
            Entity(id="second", text="汉族", type="ETHNICITY", start=16, end=18, confidence=0.95, source="has"),
        ]

        relocated = service._relocate_has_entities(entities, full_text, chunk)

        self.assertEqual([(item.start, item.end) for item in relocated], [(6, 8), (16, 18)])

    def test_query_names_are_passthrough_no_hidden_aliases(self):
        # 勾选什么查什么: the checklist owns the query vocabulary — the old
        # prompt-only alias expansion (地理位置/道路地址 silently appended to a
        # checked 地址) is gone with the registry translation layer.
        service = HaSService()
        names = service._expand_query_type_names("ADDRESS", ["地址"])

        self.assertEqual(names, ["地址"])

    def test_health_info_is_not_default_or_medical_industry_l3(self):
        default_ids = {item.id for item in get_default_generic_types()}
        self.assertNotIn("HEALTH_INFO", default_ids)

        medical = next(
            preset
            for preset in _load_builtin_presets()
            if preset.get("id") == "industry_medical_record_release"
        )
        selected = set(medical.get("selectedEntityTypeIds") or [])
        ocr_has = set(medical.get("ocrHasTypes") or [])
        # The medical-release preset redacts identity/administrative atoms and
        # deliberately keeps clinical content (diagnosis, medication, ...).
        # 2026-06-18 taxonomy: MED_INSTITUTION was removed as redundant — the
        # base INSTITUTION_NAME label covers medical institutions.
        identity_atoms = {
            "PERSON",
            "ID_CARD",
            "INSTITUTION_NAME",
            "MED_RECORD_ID",
            "INPATIENT_NO",
            "REGISTRATION_NO",
        }
        clinical_atoms = {"MED_DIAGNOSIS", "MED_MEDICATION", "MED_EXAM_RESULT"}

        self.assertNotIn("HEALTH_INFO", selected)
        self.assertNotIn("HEALTH_INFO", ocr_has)
        self.assertTrue(identity_atoms.issubset(selected))
        self.assertTrue(identity_atoms.issubset(ocr_has))
        self.assertFalse(clinical_atoms & selected)
        self.assertFalse(clinical_atoms & ocr_has)


if __name__ == "__main__":
    unittest.main()
