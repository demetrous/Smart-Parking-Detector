from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from .project_models import (
    ProjectAsset,
    ProjectCreate,
    ProjectImportResult,
    ProjectManifest,
    ProjectMedia,
    ProjectPatch,
)


PROJECTS_DIR = Path(
    os.getenv("PARKINGSPOTTER_PROJECTS_DIR", Path(__file__).resolve().parents[1] / "projects")
)

_SAFE_ID = re.compile(r"[^a-z0-9_-]+")
_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".mp4",
    ".mov",
    ".webm",
    ".mkv",
    ".json",
}
_ASSET_SUBDIR_BY_KIND = {
    "media": "assets",
    "calibration": "assets",
    "asset": "assets",
    "detections": "derived",
    "geometry": "derived",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    slug = _SAFE_ID.sub("-", value.strip().lower()).strip("-_")
    return slug or f"project-{uuid4().hex[:8]}"


def ensure_projects_dir() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    safe_id = slugify(project_id)
    if safe_id != project_id:
        raise HTTPException(status_code=400, detail="Invalid project id")
    ensure_projects_dir()
    path = (PROJECTS_DIR / safe_id).resolve()
    root = PROJECTS_DIR.resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="Invalid project path")
    return path


def manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def read_manifest(project_id: str) -> ProjectManifest:
    path = manifest_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest(manifest: ProjectManifest) -> ProjectManifest:
    path = manifest_path(manifest.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest.updatedAt = _now()
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def list_projects() -> list[ProjectManifest]:
    ensure_projects_dir()
    projects: list[ProjectManifest] = []
    for path in sorted(PROJECTS_DIR.iterdir()):
        if path.is_dir() and (path / "project.json").exists():
            try:
                projects.append(ProjectManifest.model_validate_json((path / "project.json").read_text(encoding="utf-8")))
            except Exception:
                continue
    return sorted(projects, key=lambda project: project.updatedAt, reverse=True)


def create_project(payload: ProjectCreate) -> ProjectManifest:
    project_id = slugify(payload.id or payload.name)
    path = project_dir(project_id)
    if path.exists():
        raise HTTPException(status_code=409, detail="Project already exists")
    manifest = ProjectManifest(id=project_id, name=payload.name)
    write_manifest(manifest)
    (path / "assets").mkdir(exist_ok=True)
    (path / "derived").mkdir(exist_ok=True)
    return manifest


def patch_project(project_id: str, payload: ProjectPatch) -> ProjectManifest:
    manifest = read_manifest(project_id)
    updates = payload.model_dump(exclude_unset=True)
    updated = ProjectManifest.model_validate({**manifest.model_dump(), **updates})
    return write_manifest(updated)


def _safe_asset_name(filename: str) -> str:
    raw = Path(filename or "asset").name
    suffix = Path(raw).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension: {suffix or '(none)'}")
    stem = slugify(Path(raw).stem)
    return f"{stem}-{uuid4().hex[:8]}{suffix}"


def _resolve_project_relative(project_id: str, relative_path: str) -> Path:
    base = project_dir(project_id).resolve()
    target = (base / relative_path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="Invalid asset path")
    return target


def asset_path(project_id: str, relative_path: str) -> Path:
    target = _resolve_project_relative(project_id, relative_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return target


async def save_project_asset(project_id: str, file: UploadFile, kind: str) -> ProjectAsset:
    manifest = read_manifest(project_id)
    subdir = _ASSET_SUBDIR_BY_KIND.get(kind, "assets")
    filename = _safe_asset_name(file.filename or "asset")
    relative = f"{subdir}/{filename}"
    destination = _resolve_project_relative(project_id, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            output.write(chunk)

    asset = ProjectAsset(
        path=relative,
        url=f"/projects/{project_id}/assets/{relative}",
        originalName=file.filename or filename,
        contentType=file.content_type,
        size=size,
    )

    if kind == "media":
        media_type = "video" if destination.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"} else "image"
        manifest.media = ProjectMedia(
            type=media_type,
            assetPath=relative,
            originalName=asset.originalName,
            contentType=asset.contentType,
        )
        manifest.uiState.selectedMode = media_type
    elif kind == "calibration":
        manifest.calibrationPath = relative
    elif kind == "detections":
        manifest.lastDetectionsPath = relative
    elif kind == "geometry":
        manifest.geometryLinesPath = relative
    write_manifest(manifest)
    return asset


def export_project_zip(project_id: str) -> bytes:
    base = project_dir(project_id)
    if not (base / "project.json").exists():
        raise HTTPException(status_code=404, detail="Project not found")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in base.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(base).as_posix())
    return buffer.getvalue()


async def import_project_zip(file: UploadFile) -> ProjectImportResult:
    raw = await file.read()
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid project ZIP") from exc

    names = archive.namelist()
    if "project.json" not in names:
        raise HTTPException(status_code=400, detail="Project ZIP is missing project.json")

    manifest = ProjectManifest.model_validate_json(archive.read("project.json").decode("utf-8"))
    project_id = slugify(manifest.id)
    if project_id != manifest.id:
        raise HTTPException(status_code=400, detail="Invalid project id in manifest")
    target = project_dir(project_id)
    if target.exists():
        raise HTTPException(status_code=409, detail="Project already exists")

    target.mkdir(parents=True)
    imported = 0
    try:
        for member in names:
            member_path = Path(member)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise HTTPException(status_code=400, detail="Project ZIP contains unsafe paths")
            destination = (target / member_path).resolve()
            if target.resolve() not in destination.parents and destination != target.resolve():
                raise HTTPException(status_code=400, detail="Project ZIP contains unsafe paths")
            if member.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
            imported += 1
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    manifest = read_manifest(project_id)
    return ProjectImportResult(project=manifest, importedFiles=imported)
