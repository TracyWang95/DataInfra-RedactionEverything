from __future__ import annotations

import pytest

EXPECTED = {
    ("/api/v1/dicom/ingest", "POST"),
    ("/api/v1/dicom/studies", "GET"),
    ("/api/v1/dicom/studies/{study_id}", "GET"),
    ("/api/v1/dicom/studies/{study_id}/metadata", "GET"),
    ("/api/v1/dicom/studies/{study_id}/risks", "GET"),
    ("/api/v1/dicom/studies/{study_id}/instances/{instance_id}/preview", "GET"),
    ("/api/v1/dicom/studies/{study_id}/preflight", "POST"),
    ("/api/v1/dicom/studies/{study_id}/review", "POST"),
    ("/api/v1/dicom/studies/{study_id}/anonymize", "POST"),
    ("/api/v1/dicom/jobs/{job_id}", "GET"),
    ("/api/v1/dicom/jobs/{job_id}/report", "GET"),
    ("/api/v1/dicom/jobs/{job_id}/export", "GET"),
}


def test_dicom_route_surface_matches_product_contract():
    from app.main import app

    actual = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    if not any(path.startswith("/api/v1/dicom") for path, _ in actual):
        pytest.skip("DICOM API implementation has not been merged yet")
    missing = EXPECTED - actual
    assert not missing, f"missing DICOM API route(s): {sorted(missing)}"
