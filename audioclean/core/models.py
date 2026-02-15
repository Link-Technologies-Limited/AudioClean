from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class FileRecord:
    id: int | None
    path: Path
    size: int
    mtime: float
    blake3: str | None = None
    codec: str | None = None
    container: str | None = None
    duration: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    has_art: bool = False


@dataclass
class Fingerprint:
    file_id: int
    chromaprint: str


@dataclass
class CandidateMatch:
    source: str
    recording_id: str | None
    confidence: float
    reason: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Operation:
    op_id: str
    op_type: str
    path: Path
    new_path: Path | None = None
    reason: str = ""
    sources: list[str] = field(default_factory=list)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None

    @staticmethod
    def create(
        op_type: str,
        path: Path,
        new_path: Path | None,
        reason: str,
        confidence: float | None = None,
        sources: list[str] | None = None,
        status: str = "pending",
        metadata: dict[str, Any] | None = None,
    ) -> "Operation":
        return Operation(
            op_id=str(uuid4()),
            op_type=op_type,
            path=path,
            new_path=new_path,
            reason=reason,
            confidence=confidence,
            sources=list(sources or []),
            status=status,
            metadata=dict(metadata or {}),
        )


@dataclass
class Plan:
    plan_id: str
    created_at: str
    root_paths: list[Path]
    operations: list[Operation]
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        root_paths: list[Path],
        operations: list[Operation],
        metadata: dict[str, Any] | None = None,
    ) -> "Plan":
        return Plan(
            plan_id=str(uuid4()),
            created_at=_now_iso(),
            root_paths=root_paths,
            operations=operations,
            metadata=dict(metadata or {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "root_paths": [str(p) for p in self.root_paths],
            "operations": [operation_to_dict(op) for op in self.operations],
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Plan":
        ops = [operation_from_dict(item) for item in data.get("operations", [])]
        return Plan(
            plan_id=data["plan_id"],
            created_at=data["created_at"],
            root_paths=[Path(p) for p in data.get("root_paths", [])],
            operations=ops,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class Journal:
    journal_id: str
    created_at: str
    plan_id: str
    entries: list[dict[str, Any]]

    @staticmethod
    def create(plan_id: str) -> "Journal":
        return Journal(journal_id=str(uuid4()), created_at=_now_iso(), plan_id=plan_id, entries=[])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def operation_to_dict(op: Operation) -> dict[str, Any]:
    return {
        "op_id": op.op_id,
        "op_type": op.op_type,
        "path": str(op.path),
        "new_path": str(op.new_path) if op.new_path else None,
        "reason": op.reason,
        "sources": op.sources,
        "status": op.status,
        "metadata": op.metadata,
        "confidence": op.confidence,
    }


def operation_from_dict(data: dict[str, Any]) -> Operation:
    return Operation(
        op_id=data["op_id"],
        op_type=data["op_type"],
        path=Path(data["path"]),
        new_path=Path(data["new_path"]) if data.get("new_path") else None,
        reason=data.get("reason", ""),
        sources=list(data.get("sources", [])),
        status=data.get("status", "pending"),
        metadata=dict(data.get("metadata", {})),
        confidence=data.get("confidence"),
    )
