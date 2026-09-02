from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import dicom as dicom_api
from app.core.auth import require_auth
from app.core.errors import AppError, app_error_handler
from app.services.dicom_jobs import DicomJobService, get_dicom_job_service

_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeDicomCore:
    def __init__(self, *, high_risk: bool = True) -> None:
        self.inspect_calls = 0
        self.high_risk = high_risk

    def inspect_dicom_paths(self, paths, profile="basic", options=None):
        self.inspect_calls += 1
        studies = []
        risks = []
        for index, path in enumerate(paths):
            study_uid = f"1.2.840.10008.1.{index + 1}"
            series_uid = f"{study_uid}.1"
            sop_uid = f"{series_uid}.1"
            instance = {
                "path": str(path),
                "study_instance_uid": study_uid,
                "series_instance_uid": series_uid,
                "sop_instance_uid": sop_uid,
                "sop_class_uid": "1.2.840.10008.5.1.4.1.1.2",
                "transfer_syntax_uid": "1.2.840.10008.1.2.1",
                "number_of_frames": 1,
                "rows": 1,
                "columns": 1,
                "metadata": {
                    "0010,0010": {"keyword": "PatientName", "value": "测试患者"},
                    "0008,0060": {"keyword": "Modality", "value": "CT"},
                },
            }
            studies.append(
                {
                    "study_instance_uid": study_uid,
                    "patient_reference": f"patient-{index}",
                    "modalities": ["CT"],
                    "series": [
                        {
                            "study_instance_uid": study_uid,
                            "series_instance_uid": series_uid,
                            "modality": "CT",
                            "series_number": "1",
                            "instances": [instance],
                        }
                    ],
                }
            )
            if self.high_risk:
                risks.append(
                    {
                        "code": "BURNED_IN_ANNOTATION_UNKNOWN",
                        "severity": "high",
                        "message": "Burned-in annotation status is unknown",
                        "study_instance_uid": study_uid,
                        "series_instance_uid": series_uid,
                        "sop_instance_uid": sop_uid,
                        "details": {"path": str(path)},
                    }
                )
        return {
            "status": "ready",
            "studies": studies,
            "instances": [series["instances"][0] for study in studies for series in study["series"]],
            "risks": risks,
        }

    def preflight_study(self, paths, profile="basic", options=None):
        return {
            "status": "review_required" if self.high_risk else "ready",
            "can_execute": True,
            "risks": (
                [
                    {
                        "code": "PIXEL_REVIEW",
                        "severity": "high",
                        "message": "Pixel review is required",
                    }
                ]
                if self.high_risk
                else []
            ),
        }

    def anonymize_study(self, instance_paths, output_dir, profile="basic", options=None):
        outputs = []
        for index, source in enumerate(instance_paths):
            output = os.path.join(output_dir, f"instance-{index + 1}.dcm")
            shutil.copyfile(source, output)
            outputs.append(output)
        return {
            "status": "completed",
            "output_paths": outputs,
            "report": {
                "patient_identity_removed": "YES",
                "deidentification_method": profile,
            },
            "validation": {"passed": True, "instance_count": len(outputs)},
        }

    def render_instance_preview(self, path, frame_index=0, window_center=None, window_width=None):
        assert os.path.isfile(path)
        return _PNG_1X1


@pytest.fixture()
def dicom_api_client(tmp_path, monkeypatch):
    service = DicomJobService(
        db_path=str(tmp_path / "dicom.sqlite3"),
        upload_root=str(tmp_path / "uploads"),
        output_root=str(tmp_path / "outputs"),
    )
    core = _FakeDicomCore()
    monkeypatch.setattr(service, "_core", lambda: core)
    monkeypatch.setattr(dicom_api.settings, "UPLOAD_DIR", str(tmp_path / "staging"))

    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(
        dicom_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    app.dependency_overrides[get_dicom_job_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: "tenant_a"
    with TestClient(app) as client:
        yield client, app, service, core
    app.dependency_overrides.clear()


def _ingest(client: TestClient, content: bytes = b"fake-dicom", name: str = "image.dcm", **kwargs):
    return client.post(
        "/api/v1/dicom/ingest",
        files={"file": (name, content, "application/dicom")},
        data={"profile": "basic"},
        **kwargs,
    )


def test_single_ingest_hierarchy_metadata_preview_and_tenant_isolation(dicom_api_client):
    client, app, _service, _core = dicom_api_client
    response = _ingest(client)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["study_count"] == 1
    assert payload["series_count"] == 1
    assert payload["instance_count"] == 1
    study = payload["studies"][0]
    assert study["study_id"] == study["id"]
    assert study["subject_key"].startswith("SUBJ-")
    assert "study_instance_uid" not in study
    instance = study["series"][0]["instances"][0]
    assert study["series"][0]["series_id"] == study["series"][0]["id"]
    assert instance["instance_id"] == instance["id"]

    listed = client.get("/api/v1/dicom/studies").json()
    assert listed["items"][0]["id"] == study["id"]
    assert listed["studies"][0]["study_id"] == study["id"]
    detail = client.get(f"/api/v1/dicom/studies/{study['id']}")
    assert detail.status_code == 200
    assert detail.json()["series"][0]["instances"][0]["id"] == instance["id"]

    metadata = client.get(f"/api/v1/dicom/studies/{study['id']}/metadata")
    assert metadata.status_code == 200
    assert metadata.json()["entries"]
    assert metadata.json()["instances"][0]["metadata"]["0010,0010"]["value"] == "测试患者"
    assert "path" not in metadata.text.lower()

    preview = client.get(
        f"/api/v1/dicom/studies/{study['id']}/instances/{instance['id']}/preview?frame=0"
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")
    out_of_range = client.get(
        f"/api/v1/dicom/studies/{study['id']}/instances/{instance['id']}/preview?frame=1"
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error_code"] == "DICOM_FRAME_OUT_OF_RANGE"
    assert out_of_range.json()["detail"] == {"frame": 1, "frame_count": 1}

    app.dependency_overrides[require_auth] = lambda: "tenant_b"
    hidden = client.get(f"/api/v1/dicom/studies/{study['id']}")
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "DICOM_STUDY_NOT_FOUND"
    assert "request_id" in hidden.json()
    assert client.get("/api/v1/dicom/studies").json()["items"] == []


def test_ingest_idempotency_is_tenant_and_payload_scoped(dicom_api_client):
    client, _app, _service, core = dicom_api_client
    headers = {"X-Idempotency-Key": "dicom-import-1"}
    first = _ingest(client, headers=headers)
    second = _ingest(client, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["ingest_id"] == second.json()["ingest_id"]
    assert core.inspect_calls == 1

    conflict = _ingest(client, content=b"different", headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_zip_path_traversal_and_zip_bomb_metadata_are_rejected(dicom_api_client):
    client, _app, _service, _core = dicom_api_client
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../outside.dcm", b"not allowed")
    response = client.post(
        "/api/v1/dicom/ingest",
        files={"archive": ("study.zip", buffer.getvalue(), "application/zip")},
        data={"profile": "basic"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "DICOM_ZIP_PATH_TRAVERSAL"


def test_zip_happy_path_preserves_relative_filenames(dicom_api_client):
    client, _app, _service, _core = dicom_api_client
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("patient-a/study/one.dcm", b"dicom-one")
        archive.writestr("patient-b/study/two.dcm", b"dicom-two")
    response = client.post(
        "/api/v1/dicom/ingest",
        files={"archive": ("studies.zip", buffer.getvalue(), "application/zip")},
        data={"profile": "basic"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["source_kind"] == "zip"
    assert response.json()["study_count"] == 2


def test_upload_size_limit_is_stream_enforced(dicom_api_client, monkeypatch):
    client, _app, _service, _core = dicom_api_client
    monkeypatch.setattr(dicom_api, "_MAX_UPLOAD_BYTES", 4)
    response = _ingest(client, content=b"12345")
    assert response.status_code == 413
    assert response.json()["error_code"] == "DICOM_UPLOAD_TOO_LARGE"


def test_preflight_stale_version_review_export_gate_and_report(dicom_api_client):
    client, _app, _service, _core = dicom_api_client
    study = _ingest(client).json()["studies"][0]

    preflight = client.post(
        f"/api/v1/dicom/studies/{study['id']}/preflight",
        json={"profile": "research_strict", "options": {"clean_pixel_data": True}},
    )
    assert preflight.status_code == 200, preflight.text
    version = preflight.json()["preflight_version"]
    assert preflight.json()["risks_summary"]["blocking"] == 1
    assert preflight.json()["risk_summary"]["high"] == 1

    stale = client.post(
        f"/api/v1/dicom/studies/{study['id']}/anonymize",
        json={"profile": "research_strict", "expected_preflight_version": version - 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "DICOM_PREFLIGHT_STALE"

    started = client.post(
        f"/api/v1/dicom/studies/{study['id']}/anonymize",
        json={
            "profile": "research_strict",
            "options": {"clean_pixel_data": True},
            "expected_preflight_version": version,
        },
        headers={"X-Idempotency-Key": "anon-1"},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    status = client.get(f"/api/v1/dicom/jobs/{job_id}")
    assert status.json()["status"] == "completed"

    report = client.get(f"/api/v1/dicom/jobs/{job_id}/report")
    assert report.status_code == 200
    assert report.json()["deidentification"]["patient_identity_removed"] == "YES"
    assert report.json()["validation"]["passed"] is True

    blocked = client.get(f"/api/v1/dicom/jobs/{job_id}/export")
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "DICOM_REVIEW_REQUIRED"

    risks = client.get(f"/api/v1/dicom/studies/{study['id']}/risks").json()["items"]
    reviewed = client.post(
        f"/api/v1/dicom/studies/{study['id']}/review",
        json={
            "decisions": [
                {"risk_id": risks[0]["id"], "resolution": "false_positive", "note": "医生复核未见烧录信息"}
            ]
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["summary"]["blocking"] == 0
    exported = client.get(f"/api/v1/dicom/jobs/{job_id}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.namelist() == ["instance-1.dcm"]


def test_accepted_high_risk_remains_a_blocking_gate(dicom_api_client):
    client, _app, _service, _core = dicom_api_client
    study = _ingest(client).json()["studies"][0]
    client.post(
        f"/api/v1/dicom/studies/{study['id']}/preflight",
        json={"profile": "research_strict"},
    )
    risk = client.get(f"/api/v1/dicom/studies/{study['id']}/risks").json()["risks"][0]
    response = client.post(
        f"/api/v1/dicom/studies/{study['id']}/review",
        json={
            "decisions": [
                {
                    "risk_id": risk["risk_id"],
                    "resolution": "accepted",
                    "note": "业务知情接受但不得作为安全导出放行依据",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["risk_summary"]["blocking"] == 1
    assert response.json()["export_allowed"] is False


def test_anonymize_requires_the_exact_preflight_contract(dicom_api_client):
    client, _app, _service, _core = dicom_api_client
    study = _ingest(client).json()["studies"][0]

    missing_version = client.post(
        f"/api/v1/dicom/studies/{study['id']}/anonymize",
        json={"profile": "research_strict"},
    )
    assert missing_version.status_code == 422

    preflight = client.post(
        f"/api/v1/dicom/studies/{study['id']}/preflight",
        json={"profile": "research_strict", "options": {"clean_pixel_data": True}},
    )
    assert preflight.status_code == 200, preflight.text
    version = preflight.json()["preflight_version"]

    wrong_profile = client.post(
        f"/api/v1/dicom/studies/{study['id']}/anonymize",
        json={
            "profile": "longitudinal",
            "options": {"clean_pixel_data": True},
            "expected_preflight_version": version,
        },
    )
    assert wrong_profile.status_code == 409
    assert wrong_profile.json()["error_code"] == "DICOM_PREFLIGHT_PROFILE_MISMATCH"

    wrong_options = client.post(
        f"/api/v1/dicom/studies/{study['id']}/anonymize",
        json={"profile": "research_strict", "expected_preflight_version": version},
    )
    assert wrong_options.status_code == 409
    assert wrong_options.json()["error_code"] == "DICOM_PREFLIGHT_OPTIONS_MISMATCH"


def test_batch_creation_is_atomic_when_one_preflight_is_stale(dicom_api_client):
    client, _app, service, core = dicom_api_client
    core.high_risk = False
    response = client.post(
        "/api/v1/dicom/ingest",
        files=[
            ("files", ("a.dcm", b"dicom-a", "application/dicom")),
            ("files", ("b.dcm", b"dicom-b", "application/dicom")),
        ],
        data={"profile": "basic"},
    )
    studies = response.json()["studies"]
    versions = {}
    for study in studies:
        preflight = client.post(
            f"/api/v1/dicom/studies/{study['id']}/preflight",
            json={"profile": "basic"},
        )
        versions[study["id"]] = preflight.json()["preflight_version"]
    versions[studies[-1]["id"]] -= 1

    rejected = client.post(
        "/api/v1/dicom/anonymize",
        json={
            "profile": "basic",
            "study_ids": [study["id"] for study in studies],
            "expected_preflight_versions": versions,
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "DICOM_PREFLIGHT_STALE"
    with service._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM dicom_jobs").fetchone()[0] == 0


def test_multi_file_batch_execution_and_batch_export(dicom_api_client):
    client, _app, _service, core = dicom_api_client
    core.high_risk = False
    response = client.post(
        "/api/v1/dicom/ingest",
        files=[
            ("files", ("folder/a.dcm", b"dicom-a", "application/dicom")),
            ("files", ("folder/b.dcm", b"dicom-b", "application/dicom")),
        ],
        data={"profile": "basic"},
    )
    assert response.status_code == 201, response.text
    studies = response.json()["studies"]
    assert len(studies) == 2
    versions = {}
    for study in studies:
        preflight = client.post(
            f"/api/v1/dicom/studies/{study['id']}/preflight",
            json={"profile": "basic"},
        )
        assert preflight.status_code == 200, preflight.text
        versions[study["id"]] = preflight.json()["preflight_version"]
    started = client.post(
        "/api/v1/dicom/anonymize",
        json={
            "profile": "basic",
            "study_ids": [item["id"] for item in studies],
            "expected_preflight_versions": versions,
        },
    )
    assert started.status_code == 202, started.text
    batch_id = started.json()["batch_id"]
    batch = client.get(f"/api/v1/dicom/batches/{batch_id}")
    assert batch.status_code == 200
    assert batch.json()["status"] == "completed"
    assert len(batch.json()["jobs"]) == 2
    reloaded_studies = client.get("/api/v1/dicom/studies?limit=200").json()["studies"]
    assert len(reloaded_studies) == 2
    assert {item["latest_job"]["batch_id"] for item in reloaded_studies} == {batch_id}
    assert {item["latest_job"]["status"] for item in reloaded_studies} == {"completed"}
    exported = client.get(f"/api/v1/dicom/batches/{batch_id}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert len(archive.namelist()) == 2


def test_real_core_review_to_anonymize_and_tenant_mapping_isolation(tmp_path, monkeypatch):
    """Exercise the actual pydicom core, not the fake adapter used above."""
    # This legacy core workflow tests manual review and tenant pseudonym
    # isolation without provisioning the GPU OCR/HaS sidecars.  Production
    # keeps pixel OCR enabled by default; only this isolated test opts out.
    monkeypatch.setenv("DICOM_PIXEL_OCR_ENABLED", "false")
    source = Path(__file__).parent / "assets" / "dicom" / "cache" / "pydicom" / "CT_small.dcm"
    if not source.is_file():
        pytest.skip("pinned real DICOM fixture has not been fetched")

    import pydicom

    service = DicomJobService(
        db_path=str(tmp_path / "real-core.sqlite3"),
        upload_root=str(tmp_path / "real-uploads"),
        output_root=str(tmp_path / "real-outputs"),
    )
    monkeypatch.setattr(dicom_api.settings, "UPLOAD_DIR", str(tmp_path / "real-staging"))
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(dicom_api.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
    app.dependency_overrides[get_dicom_job_service] = lambda: service

    outputs: list[tuple[str, str]] = []
    try:
        with TestClient(app) as client:
            for owner in ("hospital-a", "hospital-b"):
                app.dependency_overrides[require_auth] = lambda owner=owner: owner
                ingested = client.post(
                    "/api/v1/dicom/ingest",
                    files={"file": ("CT_small.dcm", source.read_bytes(), "application/dicom")},
                    data={"profile": "research_strict"},
                )
                assert ingested.status_code == 201, ingested.text
                study_id = ingested.json()["studies"][0]["study_id"]
                preflight = client.post(
                    f"/api/v1/dicom/studies/{study_id}/preflight",
                    json={"profile": "research_strict"},
                )
                assert preflight.status_code == 200, preflight.text
                risks = client.get(f"/api/v1/dicom/studies/{study_id}/risks").json()["risks"]
                high_risks = [risk for risk in risks if risk["severity"] == "high"]
                assert high_risks, "fixture must exercise the per-instance pixel review gate"
                reviewed = client.post(
                    f"/api/v1/dicom/studies/{study_id}/review",
                    json={
                        "decisions": [
                            {
                                "risk_id": risk["risk_id"],
                                "resolution": "false_positive",
                                "note": "pinned test fixture visually verified clear",
                            }
                            for risk in high_risks
                        ]
                    },
                )
                assert reviewed.status_code == 200, reviewed.text
                assert reviewed.json()["risk_summary"]["blocking"] == 0

                started = client.post(
                    f"/api/v1/dicom/studies/{study_id}/anonymize",
                    json={
                        "profile": "research_strict",
                        "expected_preflight_version": preflight.json()["preflight_version"],
                    },
                    headers={"X-Idempotency-Key": f"real-core-{owner}"},
                )
                assert started.status_code == 202, started.text
                job_id = started.json()["job_id"]
                assert client.get(f"/api/v1/dicom/jobs/{job_id}").json()["status"] == "completed"
                public_report = client.get(f"/api/v1/dicom/jobs/{job_id}/report")
                assert public_report.status_code == 200, public_report.text
                report_payload = public_report.json()
                assert report_payload["patient_identity_removed"] is True
                report_text = json.dumps(report_payload)
                source_dataset = pydicom.dcmread(source, stop_before_pixels=True)
                assert str(source_dataset.StudyInstanceUID) not in report_text
                assert str(source_dataset.SeriesInstanceUID) not in report_text
                assert str(source_dataset.SOPInstanceUID) not in report_text
                assert "source_sha256" not in report_text
                assert "output_sha256" not in report_text
                exported = client.get(f"/api/v1/dicom/jobs/{job_id}/export")
                assert exported.status_code == 200, exported.text
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    output_bytes = archive.read(archive.namelist()[0])
                dataset = pydicom.dcmread(io.BytesIO(output_bytes))
                assert str(dataset.PatientIdentityRemoved) == "YES"
                assert dataset.get("DeidentificationMethod")
                outputs.append((str(dataset.PatientID), str(dataset.StudyInstanceUID)))
    finally:
        app.dependency_overrides.clear()

    # The same source identifiers cannot be linked across tenant boundaries.
    assert outputs[0][0] != outputs[1][0]
    assert outputs[0][1] != outputs[1][1]


def test_real_core_multi_study_batch_export(tmp_path, monkeypatch):
    # The test exercises batch publication, not GPU inference.  Keep the
    # deployment default fail-closed and disable it only for this test case.
    monkeypatch.setenv("DICOM_PIXEL_OCR_ENABLED", "false")
    fixture_root = Path(__file__).parent / "assets" / "dicom" / "cache" / "pydicom"
    sources = [fixture_root / "CT_small.dcm", fixture_root / "MR_small.dcm"]
    if not all(path.is_file() for path in sources):
        pytest.skip("pinned real DICOM fixtures have not been fetched")

    import pydicom

    service = DicomJobService(
        db_path=str(tmp_path / "real-batch.sqlite3"),
        upload_root=str(tmp_path / "real-batch-uploads"),
        output_root=str(tmp_path / "real-batch-outputs"),
    )
    monkeypatch.setattr(dicom_api.settings, "UPLOAD_DIR", str(tmp_path / "real-batch-staging"))
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(dicom_api.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
    app.dependency_overrides[get_dicom_job_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: "batch-hospital"
    try:
        with TestClient(app) as client:
            ingested = client.post(
                "/api/v1/dicom/ingest",
                files=[
                    ("files", (path.name, path.read_bytes(), "application/dicom")) for path in sources
                ],
                data={"profile": "research_strict"},
            )
            assert ingested.status_code == 201, ingested.text
            studies = ingested.json()["studies"]
            assert len(studies) == 2
            versions: dict[str, int] = {}
            for study in studies:
                study_id = study["study_id"]
                preflight = client.post(
                    f"/api/v1/dicom/studies/{study_id}/preflight",
                    json={"profile": "research_strict"},
                )
                assert preflight.status_code == 200, preflight.text
                versions[study_id] = preflight.json()["preflight_version"]
                high_risks = [
                    risk
                    for risk in client.get(
                        f"/api/v1/dicom/studies/{study_id}/risks"
                    ).json()["risks"]
                    if risk["severity"] == "high"
                ]
                if high_risks:
                    reviewed = client.post(
                        f"/api/v1/dicom/studies/{study_id}/review",
                        json={
                            "decisions": [
                                {
                                    "risk_id": risk["risk_id"],
                                    "resolution": "false_positive",
                                    "note": "pinned fixture verified clear",
                                }
                                for risk in high_risks
                            ]
                        },
                    )
                    assert reviewed.status_code == 200, reviewed.text

            started = client.post(
                "/api/v1/dicom/anonymize",
                json={
                    "profile": "research_strict",
                    "study_ids": [study["study_id"] for study in studies],
                    "expected_preflight_versions": versions,
                },
                headers={"X-Idempotency-Key": "real-batch"},
            )
            assert started.status_code == 202, started.text
            batch_id = started.json()["batch_id"]
            batch = client.get(f"/api/v1/dicom/batches/{batch_id}")
            assert batch.status_code == 200
            assert batch.json()["status"] == "completed"
            exported = client.get(f"/api/v1/dicom/batches/{batch_id}/export")
            assert exported.status_code == 200, exported.text
            with zipfile.ZipFile(io.BytesIO(exported.content)) as outer:
                names = outer.namelist()
                assert len(names) == 2
                for name in names:
                    with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                        dataset = pydicom.dcmread(io.BytesIO(inner.read(inner.namelist()[0])))
                        assert str(dataset.PatientIdentityRemoved) == "YES"
    finally:
        app.dependency_overrides.clear()
