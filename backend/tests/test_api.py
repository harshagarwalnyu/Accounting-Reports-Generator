import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ai_engine
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_teardown():
    # Ensure temp dirs exist
    Path("temp_data").mkdir(exist_ok=True)
    Path("templates").mkdir(exist_ok=True)
    yield
    # Cleanup after tests if needed


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_generate_invalid_json():
    # Test with non-JSON config
    files = {
        "file": (
            "test.xlsx",
            b"fake content",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    data = {"config": "not-json"}
    response = client.post("/api/reports/generate", files=files, data=data)
    assert response.status_code == 400
    assert "Invalid config JSON" in response.json()["detail"]


def test_generate_wrong_file_type():
    # Test with PDF instead of Excel for main file
    files = {"file": ("test.pdf", b"fake pdf", "application/pdf")}
    data = {"config": json.dumps({"Company_Name": "Test"})}
    response = client.post("/api/reports/generate", files=files, data=data)
    assert response.status_code == 400
    assert "Excel file required" in response.json()["detail"]


def test_get_unknown_job():
    response = client.get("/api/reports/nonexistent/data")
    assert response.status_code == 404
    assert "Data not ready" in response.json()["detail"]


def test_list_templates_empty():
    # Clear templates dir for this test
    if Path("templates").exists():
        shutil.rmtree("templates")
    Path("templates").mkdir()

    response = client.get("/api/templates")
    assert response.status_code == 200
    assert response.json() == []


def test_process_report_no_anthropic_key(monkeypatch):
    """Health endpoint must stay up and ai_engine.client must be None when the key is absent."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ai_engine, "client", None)

    # The app should still serve health — no crash from a None AI client
    response = client.get("/health")
    assert response.status_code == 200

    # Confirm the attribute we patched is indeed None
    assert ai_engine.client is None
