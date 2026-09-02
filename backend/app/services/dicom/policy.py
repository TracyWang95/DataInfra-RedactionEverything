"""DICOM PS3.15-style configurable attribute policy engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydicom.datadict import tag_for_keyword
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence
from pydicom.tag import BaseTag, Tag

from app.models.dicom_schemas import DICOMPolicy, DICOMTagAction, DICOMTagChange, DICOMTagRule

from .mapping import StableDICOMMapper

# Deliberately explicit and conservative.  Custom rules supplied by the caller
# override these defaults.  The list covers common patient, order, institution,
# operator and free-text fields encountered in CT/MR/CR/DX objects.
_REMOVE_KEYWORDS = {
    "IssuerOfPatientID",
    "IssuerOfPatientIDQualifiersSequence",
    "OtherPatientIDsSequence",
    "OtherPatientNames",
    "PatientBirthName",
    "PatientAddress",
    "PatientMotherBirthName",
    "PatientTelephoneNumbers",
    "PatientTelecomInformation",
    "MedicalRecordLocator",
    "ResponsiblePerson",
    "ResponsiblePersonRole",
    "ResponsibleOrganization",
    "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    "ReferringPhysicianIdentificationSequence",
    "ConsultingPhysicianName",
    "ConsultingPhysicianIdentificationSequence",
    "PhysiciansOfRecordIdentificationSequence",
    "PhysiciansReadingStudyIdentificationSequence",
    "OperatorsIdentificationSequence",
    "RequestingPhysicianIdentificationSequence",
    "ScheduledPerformingPhysicianIdentificationSequence",
    "PerformingPhysicianIdentificationSequence",
    "HumanPerformerCodeSequence",
    "PersonIdentificationCodeSequence",
    "SourcePatientGroupIdentificationSequence",
    "GroupOfPatientsIdentificationSequence",
    "PatientInsurancePlanCodeSequence",
}

_EMPTY_KEYWORDS = {
    "PatientName",
    "PatientBirthTime",
    "PatientSex",
    "PatientAge",
    "PatientSize",
    "PatientWeight",
    "EthnicGroup",
    "Occupation",
    "AdditionalPatientHistory",
    "AdmissionID",
    "IssuerOfAdmissionID",
    "ServiceEpisodeID",
    "ReferringPhysicianName",
    "NameOfPhysiciansReadingStudy",
    "PhysiciansOfRecord",
    "PerformingPhysicianName",
    "OperatorsName",
    "RequestingPhysician",
    "ScheduledPerformingPhysicianName",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "StudyDescription",
    "StudyComments",
    "SeriesDescription",
    "ProtocolName",
    "RequestedProcedureDescription",
    "ScheduledProcedureStepDescription",
    "ImageComments",
    "AcquisitionComments",
    "DerivationDescription",
}

_DUMMY_KEYWORDS = {
    "PatientID",
    "AccessionNumber",
    "StudyID",
    "RequestedProcedureID",
    "ScheduledProcedureStepID",
    "PerformedProcedureStepID",
    "PlacerOrderNumberImagingServiceRequest",
    "FillerOrderNumberImagingServiceRequest",
}

_DEVICE_KEYWORDS = {
    "DeviceSerialNumber",
    "DeviceUID",
    "PlateID",
    "GeneratorID",
    "CassetteID",
    "GantryID",
}

_INSTITUTION_KEYWORDS = {
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
}

_DESCRIPTOR_KEYWORDS = {
    "StudyDescription",
    "StudyComments",
    "SeriesDescription",
    "ProtocolName",
    "RequestedProcedureDescription",
    "ScheduledProcedureStepDescription",
    "ImageComments",
    "AcquisitionComments",
    "DerivationDescription",
}

_PATIENT_CHARACTERISTIC_KEYWORDS = {
    "PatientAge",
    "PatientSex",
    "PatientSize",
    "PatientWeight",
    "EthnicGroup",
    "SmokingStatus",
    "PregnancyStatus",
}

_IDENTITY_UID_KEYWORDS = {
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SOPInstanceUID",
    "FrameOfReferenceUID",
    "SynchronizationFrameOfReferenceUID",
    "ReferencedSOPInstanceUID",
    "ReferencedFrameOfReferenceUID",
    "RelatedFrameOfReferenceUID",
    "ConcatenationUID",
    "IrradiationEventUID",
    "AcquisitionUID",
    "DimensionOrganizationUID",
    "TrackingUID",
    "SpecimenUID",
    "FiducialUID",
}

_PRESERVE_UID_KEYWORDS = {
    "SOPClassUID",
    "ReferencedSOPClassUID",
    "MediaStorageSOPClassUID",
    "TransferSyntaxUID",
    "ImplementationClassUID",
    "CodingSchemeUID",
    "ContextGroupExtensionCreatorUID",
}

_DATE_VRS = {"DA", "DT"}
_TAG_PATTERN = re.compile(r"^\(?([0-9A-Fa-f]{4})[, ]?([0-9A-Fa-f]{4})\)?$")


def _selector_tag(selector: str) -> BaseTag | None:
    text = selector.strip()
    match = _TAG_PATTERN.fullmatch(text)
    if match:
        return Tag(int(match.group(1), 16), int(match.group(2), 16))
    value = tag_for_keyword(text)
    return Tag(value) if value is not None else None


def _default_rules() -> list[DICOMTagRule]:
    rules: list[DICOMTagRule] = []
    rules.extend(DICOMTagRule(selector=key, action=DICOMTagAction.REMOVE) for key in sorted(_REMOVE_KEYWORDS))
    rules.extend(DICOMTagRule(selector=key, action=DICOMTagAction.EMPTY) for key in sorted(_EMPTY_KEYWORDS))
    rules.extend(DICOMTagRule(selector=key, action=DICOMTagAction.DUMMY) for key in sorted(_DUMMY_KEYWORDS))
    rules.extend(DICOMTagRule(selector=key, action=DICOMTagAction.UID) for key in sorted(_IDENTITY_UID_KEYWORDS))
    return rules


def build_policy(profile: str = "basic", options: dict[str, Any] | None = None) -> DICOMPolicy:
    """Build a validated policy from a named preset and JSON-like overrides."""

    options = dict(options or {})
    normalized = str(profile or "basic").strip().lower()
    if normalized not in {"basic", "research", "longitudinal", "strict"}:
        raise ValueError(f"Unsupported DICOM profile: {profile}")

    raw_rules = options.pop("rules", []) or []
    custom_rules = [rule if isinstance(rule, DICOMTagRule) else DICOMTagRule.model_validate(rule) for rule in raw_rules]
    policy_values: dict[str, Any] = {
        "profile": normalized,
        "rules": _default_rules(),
    }
    if normalized == "strict":
        policy_values["retain_longitudinal_dates"] = False
        policy_values["date_mode"] = "remove"
    policy_fields = set(DICOMPolicy.model_fields)
    policy_values.update({key: value for key, value in options.items() if key in policy_fields})
    policy = DICOMPolicy.model_validate(policy_values)
    if "date_mode" not in options:
        policy.date_mode = "shift" if policy.retain_longitudinal_dates else "remove"
    policy.retain_longitudinal_dates = policy.date_mode != "remove"

    # Patient Birth Date participates in the same deterministic date shift as
    # Study/Series dates when longitudinal timing is retained; strict profiles
    # replace it with a zero-length value.
    policy.rules.append(
        DICOMTagRule(
            selector="PatientBirthDate",
            action={
                "shift": DICOMTagAction.CLEAN,
                "retain": DICOMTagAction.KEEP,
                "remove": DICOMTagAction.EMPTY,
            }[policy.date_mode],
            reason="longitudinal date policy",
        )
    )

    # Retention options are represented as explicit K rules so they override
    # the conservative defaults using the last-rule-wins lookup below.
    if policy.retain_patient_characteristics:
        policy.rules.extend(
            DICOMTagRule(selector=key, action=DICOMTagAction.KEEP, reason="retain patient characteristics option")
            for key in sorted(_PATIENT_CHARACTERISTIC_KEYWORDS)
        )
    if policy.retain_device_identity:
        policy.rules.extend(
            DICOMTagRule(selector=key, action=DICOMTagAction.KEEP, reason="retain device identity option")
            for key in sorted(_DEVICE_KEYWORDS)
        )
    else:
        policy.rules.extend(DICOMTagRule(selector=key, action=DICOMTagAction.EMPTY) for key in sorted(_DEVICE_KEYWORDS))
    if policy.retain_institution_identity:
        policy.rules.extend(
            DICOMTagRule(selector=key, action=DICOMTagAction.KEEP, reason="retain institution identity option")
            for key in sorted(_INSTITUTION_KEYWORDS)
        )
    if policy.retain_uids:
        policy.rules.extend(
            DICOMTagRule(selector=key, action=DICOMTagAction.KEEP, reason="retain UIDs option")
            for key in sorted(_IDENTITY_UID_KEYWORDS)
        )
    if not policy.clean_descriptors:
        policy.rules.extend(
            DICOMTagRule(selector=key, action=DICOMTagAction.KEEP, reason="descriptor cleaning disabled")
            for key in sorted(_DESCRIPTOR_KEYWORDS)
        )
    # Caller-supplied rules are authoritative and therefore applied last.
    policy.rules.extend(custom_rules)
    return policy


@dataclass
class PolicyApplication:
    changes: list[DICOMTagChange] = field(default_factory=list)
    action_counts: dict[str, int] = field(default_factory=dict)
    private_tags_removed: int = 0
    date_values_shifted: int = 0

    def record(self, change: DICOMTagChange) -> None:
        self.changes.append(change)
        self.action_counts[change.action.value] = self.action_counts.get(change.action.value, 0) + 1


class DICOMPolicyEngine:
    def __init__(self, policy: DICOMPolicy, mapper: StableDICOMMapper) -> None:
        self.policy = policy
        self.mapper = mapper
        self._rules_by_tag: dict[BaseTag, DICOMTagRule] = {}
        self._rules_by_keyword: dict[str, DICOMTagRule] = {}
        for rule in policy.rules:
            tag = _selector_tag(rule.selector)
            if tag is not None:
                self._rules_by_tag[tag] = rule
            self._rules_by_keyword[rule.selector.strip()] = rule
        self._safe_private_tags = {
            tag for selector in policy.safe_private_tags if (tag := _selector_tag(selector)) is not None
        }
        # A private data element is uninterpretable without its block creator.
        # Retaining an explicitly approved element therefore retains only its
        # corresponding creator as well, never the whole private group.
        self._safe_private_tags.update(
            Tag(tag.group, tag.element >> 8)
            for tag in tuple(self._safe_private_tags)
            if tag.is_private and tag.element >= 0x1000
        )

    def apply(self, dataset: Any, *, patient_key: str) -> PolicyApplication:
        result = PolicyApplication()
        self._process_dataset(dataset, patient_key=patient_key, base_path="", result=result)
        return result

    def _rule_for(self, element: Any) -> DICOMTagRule | None:
        explicit = self._rules_by_tag.get(element.tag) or self._rules_by_keyword.get(element.keyword or "")
        if explicit is not None:
            return explicit
        if element.tag in self._safe_private_tags:
            return DICOMTagRule(
                selector=str(element.tag),
                action=DICOMTagAction.KEEP,
                reason="approved safe private attribute",
            )
        if element.VR == "UI" and self.policy.retain_uids:
            return DICOMTagRule(
                selector=str(element.tag),
                action=DICOMTagAction.KEEP,
                reason="retain UIDs option",
            )
        if element.VR == "UI" and self._should_remap_uid(element.keyword or ""):
            return DICOMTagRule(selector=str(element.tag), action=DICOMTagAction.UID, reason="identity/reference UID")
        if element.VR in _DATE_VRS:
            action = {
                "shift": DICOMTagAction.CLEAN,
                "retain": DICOMTagAction.KEEP,
                "remove": DICOMTagAction.EMPTY,
            }[self.policy.date_mode]
            return DICOMTagRule(selector=str(element.tag), action=action, reason="longitudinal date policy")
        return None

    @staticmethod
    def _should_remap_uid(keyword: str) -> bool:
        if (
            keyword in _PRESERVE_UID_KEYWORDS
            or "SOPClassUID" in keyword
            or "TransferSyntaxUID" in keyword
            or keyword in {"MappingResourceUID", "ContextGroupExtensionCreatorUID"}
        ):
            return False
        # PS3.15 assigns U to identity/reference UIDs.  Remapping every other
        # non-semantic UI is safer than a suffix allow-list and also catches
        # less common references such as Instance Creator UID and tracking UIDs.
        return True

    def _process_dataset(
        self,
        dataset: Any,
        *,
        patient_key: str,
        base_path: str,
        result: PolicyApplication,
    ) -> None:
        for element in list(dataset):
            tag_text = f"{element.tag.group:04X},{element.tag.element:04X}"
            path = f"{base_path}/{tag_text}" if base_path else tag_text

            if element.tag.is_private and element.tag not in self._safe_private_tags:
                if self.policy.remove_private_tags:
                    del dataset[element.tag]
                    result.private_tags_removed += 1
                    result.record(
                        DICOMTagChange(
                            path=path,
                            tag=tag_text,
                            keyword=element.keyword or "",
                            vr=element.VR,
                            action=DICOMTagAction.REMOVE,
                            reason="private tag policy",
                        )
                    )
                    continue

            rule = self._rule_for(element)
            if element.VR == "SQ":
                if rule and rule.action == DICOMTagAction.REMOVE:
                    del dataset[element.tag]
                    result.record(self._change(path, tag_text, element, rule))
                    continue
                if rule and rule.action in {DICOMTagAction.EMPTY, DICOMTagAction.DUMMY}:
                    element.value = Sequence()
                    result.record(self._change(path, tag_text, element, rule))
                    continue
                # Retained sequences are always traversed.  A nested identifier
                # must not escape merely because its parent sequence is kept.
                for index, item in enumerate(element.value or []):
                    self._process_dataset(
                        item,
                        patient_key=patient_key,
                        base_path=f"{path}[{index}]",
                        result=result,
                    )
                continue

            if rule is None or rule.action == DICOMTagAction.KEEP:
                continue
            self._apply_scalar(dataset, element, rule, patient_key=patient_key)
            result.record(self._change(path, tag_text, element, rule))
            if rule.action == DICOMTagAction.CLEAN and element.VR in _DATE_VRS:
                result.date_values_shifted += 1

    @staticmethod
    def _change(path: str, tag_text: str, element: Any, rule: DICOMTagRule) -> DICOMTagChange:
        return DICOMTagChange(
            path=path,
            tag=tag_text,
            keyword=element.keyword or "",
            vr=element.VR,
            action=rule.action,
            reason=rule.reason,
        )

    def _apply_scalar(self, dataset: Any, element: Any, rule: DICOMTagRule, *, patient_key: str) -> None:
        if rule.action == DICOMTagAction.REMOVE:
            del dataset[element.tag]
            return
        if rule.action == DICOMTagAction.EMPTY:
            element.value = ""
            return
        if rule.action == DICOMTagAction.UID:
            values = list(element.value) if isinstance(element.value, MultiValue) else [element.value]
            mapped = [self.mapper.uid(str(value)) for value in values]
            element.value = mapped if isinstance(element.value, MultiValue) else mapped[0]
            return
        if rule.action == DICOMTagAction.CLEAN:
            if element.VR == "DA":
                element.value = self._map_values(element.value, lambda value: self.mapper.shift_da(value, patient_key))
            elif element.VR == "DT":
                element.value = self._map_values(element.value, lambda value: self.mapper.shift_dt(value, patient_key))
            else:
                element.value = rule.value if rule.value is not None else "CLEANED"
            return
        if rule.action == DICOMTagAction.DUMMY:
            element.value = rule.value if rule.value is not None else self._dummy_value(element, patient_key)

    @staticmethod
    def _map_values(value: Any, mapper: Any) -> Any:
        if isinstance(value, MultiValue):
            return [mapper(item) for item in value]
        return mapper(value)

    def _dummy_value(self, element: Any, patient_key: str) -> Any:
        keyword = element.keyword or ""
        original = str(element.value or keyword)
        if keyword == "PatientID":
            return self.mapper.patient_pseudonym(patient_key)
        if element.VR == "PN":
            return "ANON"
        if element.VR == "UI":
            return self.mapper.uid(original)
        if element.VR == "DA":
            return "19000101"
        if element.VR == "DT":
            return "19000101000000"
        if element.VR == "TM":
            return "000000"
        if element.VR in {"US", "SS", "UL", "SL", "FL", "FD", "IS", "DS"}:
            return 0
        if element.VR in {"OB", "OW", "OF", "OD", "UN"}:
            return b""
        prefix = "A" if keyword == "AccessionNumber" else "R"
        length = 12 if element.VR in {"AE", "CS", "SH"} else 20
        return self.mapper.token(keyword or "attribute", original, prefix=prefix, length=length)


def summarize_policy_actions(dataset: Any, policy: DICOMPolicy) -> dict[str, Any]:
    """Dry-run the policy selector without copying or mutating attribute values."""

    engine = DICOMPolicyEngine(policy, StableDICOMMapper(b"policy-summary-only-secret", namespace="summary"))
    counts: dict[str, int] = {}
    matched: list[dict[str, str]] = []

    def visit(current: Any, base_path: str = "") -> None:
        for element in current:
            tag_text = f"{element.tag.group:04X},{element.tag.element:04X}"
            path = f"{base_path}/{tag_text}" if base_path else tag_text
            if element.tag.is_private and policy.remove_private_tags and element.tag not in engine._safe_private_tags:
                action = DICOMTagAction.REMOVE
                reason = "private tag policy"
            else:
                rule = engine._rule_for(element)
                action = rule.action if rule is not None else None
                reason = rule.reason if rule is not None else ""
            if action is not None and action != DICOMTagAction.KEEP:
                counts[action.value] = counts.get(action.value, 0) + 1
                if len(matched) < 200:
                    matched.append(
                        {
                            "path": path,
                            "tag": tag_text,
                            "keyword": element.keyword or "",
                            "vr": element.VR,
                            "action": action.value,
                            "reason": reason,
                        }
                    )
                if element.VR == "SQ" and action in {
                    DICOMTagAction.REMOVE,
                    DICOMTagAction.EMPTY,
                    DICOMTagAction.DUMMY,
                }:
                    continue
            if element.VR == "SQ":
                for index, item in enumerate(element.value or []):
                    visit(item, f"{path}[{index}]")

    visit(dataset)
    return {"planned_action_counts": dict(sorted(counts.items())), "planned_actions": matched}


__all__ = ["DICOMPolicyEngine", "PolicyApplication", "build_policy", "summarize_policy_actions"]
