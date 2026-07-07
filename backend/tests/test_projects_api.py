from __future__ import annotations

import shutil

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
