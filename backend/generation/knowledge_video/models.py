from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GeneratedVideoPackage:
    code: str
    scene_name: str
    subtitles: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    success: bool
    video_path: Optional[Path]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class KnowledgeVideoRequest:
    topic: str
    subject: str = ""
    source_markdown: str = ""
    source_archive_id: int = 0
    duration_seconds: int = 30
    style: str = "clean"
    requirements: str = ""
    quality: str = "low"

