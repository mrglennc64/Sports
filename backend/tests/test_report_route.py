from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_report_route_missing_file_is_friendly():
    client = TestClient(app)
    resp = client.get("/v2/report")
    assert resp.status_code == 200
    assert "report" in resp.text


def test_report_route_serves_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "lines_csv", str(tmp_path / "lines.csv"))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report-latest.txt").write_text("BACKTEST REPORT test-marker", encoding="utf-8")
    client = TestClient(app)
    resp = client.get("/v2/report")
    assert resp.status_code == 200
    assert "test-marker" in resp.text
