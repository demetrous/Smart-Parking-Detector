from __future__ import annotations

import io
import json
import os
import shutil
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import db, main, project_store
from app.hub import Hub
from app.store import SpotStore


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "projects.db")
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("SIMULATOR", "false")
    monkeypatch.setattr(main, "store", SpotStore())
    monkeypatch.setattr(main, "hub", Hub())
    monkeypatch.setattr(main, "dwell_checker_loop", lambda: _noop_loop())
    app = main.create_app()
    with TestClient(app) as test_client:
        yield test_client


async def _noop_loop() -> None:
    return None


def test_project_create_upload_asset_and_list(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "First Ave Test"})

    assert created.status_code == 200
    project = created.json()
    assert project["id"] == "first-ave-test"

    upload = client.post(
        f"/projects/{project['id']}/assets?kind=media",
        files={"file": ("street.png", b"fake image", "image/png")},
    )

    assert upload.status_code == 200
    asset = upload.json()
    assert asset["path"].startswith("assets/")

    manifest = client.get(f"/projects/{project['id']}").json()
    assert manifest["media"]["assetPath"] == asset["path"]

    asset_response = client.get(asset["url"])
    assert asset_response.status_code == 200
    assert asset_response.content == b"fake image"

    listing = client.get("/projects")
    assert listing.status_code == 200
    assert listing.json()["projects"][0]["id"] == project["id"]


def test_project_export_and_import_zip(client: TestClient, tmp_path) -> None:
    project = client.post("/projects", json={"name": "Portable"}).json()
    client.post(
        f"/projects/{project['id']}/assets?kind=calibration",
        files={"file": ("calibration.json", b'{"camera_id":"cam"}', "application/json")},
    )

    exported = client.get(f"/projects/{project['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")

    shutil.rmtree(tmp_path / "projects" / project["id"])
    imported = client.post(
        "/projects/import",
        files={"file": ("portable.zip", exported.content, "application/zip")},
    )

    assert imported.status_code == 200
    assert imported.json()["project"]["id"] == project["id"]
    assert client.get(f"/projects/{project['id']}").status_code == 200


def test_project_rejects_path_traversal(client: TestClient) -> None:
    response = client.get("/projects/../../assets/secret.txt")

    assert response.status_code in {400, 404}


# --- R0.1: operator token and size limits ---------------------------------

TOKEN = "test-projects-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest_json(project_id: str) -> bytes:
    return json.dumps({"id": project_id, "name": project_id}).encode("utf-8")


def test_project_writes_require_token_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_PROJECTS_TOKEN", TOKEN)
    zip_payload = _zip_bytes({"project.json": _manifest_json("zipped")})

    writes = [
        lambda headers: client.post("/projects", json={"name": "Locked"}, headers=headers),
        lambda headers: client.patch("/projects/locked", json={"name": "Renamed"}, headers=headers),
        lambda headers: client.post(
            "/projects/locked/assets?kind=media",
            files={"file": ("street.png", b"fake image", "image/png")},
            headers=headers,
        ),
        lambda headers: client.post(
            "/projects/import",
            files={"file": ("p.zip", zip_payload, "application/zip")},
            headers=headers,
        ),
    ]
    for send in writes:
        missing = send({})
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"
        assert send({"Authorization": "Bearer wrong-token"}).status_code == 401
        assert send({"Authorization": f"Basic {TOKEN}"}).status_code == 401

    assert not (project_store.PROJECTS_DIR / "locked").exists()
    assert not (project_store.PROJECTS_DIR / "zipped").exists()

    created = client.post("/projects", json={"name": "Locked"}, headers=AUTH)
    assert created.status_code == 200
    assert client.patch("/projects/locked", json={"name": "Renamed"}, headers=AUTH).status_code == 200
    upload = client.post(
        "/projects/locked/assets?kind=media",
        files={"file": ("street.png", b"fake image", "image/png")},
        headers=AUTH,
    )
    assert upload.status_code == 200
    imported = client.post(
        "/projects/import",
        files={"file": ("p.zip", zip_payload, "application/zip")},
        headers=AUTH,
    )
    assert imported.status_code == 200

    # Reads stay open.
    assert client.get("/projects").status_code == 200
    assert client.get("/projects/locked").status_code == 200
    assert client.get(upload.json()["url"]).status_code == 200
    assert client.get("/projects/locked/export").status_code == 200


def test_project_writes_open_without_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARKINGSPOTTER_PROJECTS_TOKEN", raising=False)

    assert client.post("/projects", json={"name": "Open"}).status_code == 200


def test_missing_token_logs_startup_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("PARKINGSPOTTER_PROJECTS_TOKEN", raising=False)
    with caplog.at_level("WARNING", logger="app.projects_auth"):
        main.create_app()
    assert "PARKINGSPOTTER_PROJECTS_TOKEN is not set" in caplog.text

    caplog.clear()
    monkeypatch.setenv("PARKINGSPOTTER_PROJECTS_TOKEN", TOKEN)
    with caplog.at_level("WARNING", logger="app.projects_auth"):
        main.create_app()
    assert "PARKINGSPOTTER_PROJECTS_TOKEN" not in caplog.text


def test_oversized_asset_upload_is_rejected_without_leftovers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = client.post("/projects", json={"name": "Capped"}).json()
    before = client.get(f"/projects/{project['id']}").json()
    monkeypatch.setenv("PARKINGSPOTTER_MAX_UPLOAD_MB", "0.001")  # ~1 KB

    response = client.post(
        f"/projects/{project['id']}/assets?kind=media",
        files={"file": ("street.png", b"x" * 4096, "image/png")},
    )

    assert response.status_code == 413
    assets_dir = project_store.PROJECTS_DIR / project["id"] / "assets"
    assert not assets_dir.exists() or not any(assets_dir.iterdir())
    assert client.get(f"/projects/{project['id']}").json() == before


def test_oversized_content_length_is_rejected_before_body_is_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import projects_auth

    client.post("/projects", json={"name": "Declared"})
    limit = projects_auth.max_upload_bytes() + projects_auth.MULTIPART_OVERHEAD_BYTES
    calls: list[str] = []
    real_save = main.save_project_asset

    async def spy_save(*args, **kwargs):
        calls.append("called")
        return await real_save(*args, **kwargs)

    monkeypatch.setattr(main, "save_project_asset", spy_save)

    response = client.post(
        "/projects/declared/assets?kind=media",
        content=b"--x--\r\n",
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Content-Length": str(limit + 1),
        },
    )

    assert response.status_code == 413
    assert calls == []


def test_oversized_json_write_is_rejected(client: TestClient) -> None:
    response = client.post("/projects", json={"name": "x" * (2 * 1024 * 1024)})

    assert response.status_code == 413
    assert client.get("/projects").json()["projects"] == []


def test_streamed_body_over_limit_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import projects_auth

    monkeypatch.setattr(projects_auth, "MAX_JSON_BODY_BYTES", 64)

    def chunks():
        yield b'{"name": "'
        yield b"y" * 256
        yield b'"}'

    # A generator body is sent chunked, without Content-Length.
    response = client.post("/projects", content=chunks(), headers={"Content-Type": "application/json"})

    assert response.status_code == 413
    assert client.get("/projects").json()["projects"] == []


def test_zip_with_too_many_entries_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_MAX_ZIP_ENTRIES", "3")
    entries = {"project.json": _manifest_json("crowded")}
    entries.update({f"assets/{i}.json": b"{}" for i in range(5)})

    response = client.post(
        "/projects/import",
        files={"file": ("crowded.zip", _zip_bytes(entries), "application/zip")},
    )

    assert response.status_code == 413
    assert not (project_store.PROJECTS_DIR / "crowded").exists()


def test_zip_over_uncompressed_limit_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_MAX_ZIP_UNCOMPRESSED_MB", "1")
    payload = _zip_bytes(
        {"project.json": _manifest_json("bomb"), "assets/big.json": b"0" * (2 * 1024 * 1024)}
    )
    assert len(payload) < 64 * 1024  # small on the wire, large once expanded

    response = client.post(
        "/projects/import",
        files={"file": ("bomb.zip", payload, "application/zip")},
    )

    assert response.status_code == 413
    assert not (project_store.PROJECTS_DIR / "bomb").exists()


def test_zip_file_over_upload_limit_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_MAX_UPLOAD_MB", "0.01")  # ~10 KB
    payload = _zip_bytes({"project.json": _manifest_json("heavy"), "assets/noise.json": os.urandom(64 * 1024)})

    response = client.post(
        "/projects/import",
        files={"file": ("heavy.zip", payload, "application/zip")},
    )

    assert response.status_code == 413
    assert not (project_store.PROJECTS_DIR / "heavy").exists()
