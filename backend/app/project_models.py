from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


ProjectMediaType = Literal["image", "video", "synthetic"]


class ProjectMedia(BaseModel):
    type: ProjectMediaType = "image"
    assetPath: str | None = None
    originalName: str | None = None
    contentType: str | None = None


class ProjectUiState(BaseModel):
    topPanePercent: float = Field(default=67, ge=20, le=90)
    selectedMode: ProjectMediaType = "image"


class ProjectManifest(BaseModel):
    schemaVersion: int = 1
    id: str
    name: str
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    media: ProjectMedia | None = None
    calibrationPath: str | None = None
    lastDetectionsPath: str | None = None
    geometryLinesPath: str | None = None
    uiState: ProjectUiState = Field(default_factory=ProjectUiState)


class ProjectCreate(BaseModel):
    id: str | None = None
    name: str


class ProjectPatch(BaseModel):
    name: str | None = None
    media: ProjectMedia | None = None
    calibrationPath: str | None = None
    lastDetectionsPath: str | None = None
    geometryLinesPath: str | None = None
    uiState: ProjectUiState | None = None


class ProjectAsset(BaseModel):
    path: str
    url: str
    originalName: str
    contentType: str | None = None
    size: int


class ProjectImportResult(BaseModel):
    project: ProjectManifest
    importedFiles: int


class ProjectListResponse(BaseModel):
    projects: list[ProjectManifest]


class ProjectAssetKind(BaseModel):
    kind: Literal["media", "calibration", "detections", "geometry", "asset"] = "asset"
    metadata: dict[str, Any] = Field(default_factory=dict)
