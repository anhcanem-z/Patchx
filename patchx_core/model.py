# -*- coding: utf-8 -*-
"""Mo hinh du lieu: Section (khối lệnh) va Patch (tệp patch)."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    """Mot bang chung quan sat duoc trong APK da giai ma."""

    kind: str
    value: str
    source: str = ""
    weight: float = 0.5
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "source": self.source,
            "weight": self.weight,
            "details": self.details,
        }


@dataclass
class Behavior:
    """Mot nhóm hanh vi duoc phat hien tu cac bang chung."""

    name: str
    evidence: List[Evidence] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.evidence:
            return 0.0
        return round(
            sum(item.weight for item in self.evidence) / len(self.evidence),
            4,
        )

    def add_evidence(self, evidence: Evidence) -> None:
        self.evidence.append(evidence)

    def add_suggestions(self, suggestions: List[str]) -> None:
        if suggestions:
            self.suggestions.extend(suggestions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "suggestions": self.suggestions,
        }


@dataclass
class Section:
    """Mot khối lệnh trong patch.txt.

    body: anh xa khoa -> gia tri; gia tri giu nguyen thut le noi dung
          (dong dau duoc cat thut le cua tệp, cac dong tiep theo giu nguyen).
    """

    type: str
    body: Dict[str, str]
    order: int
    closed: bool = True
    name: Optional[str] = None
    raw: str = ""

    def get(self, key: str, default: str = "") -> str:
        return self.body.get(key, default)


@dataclass
class Patch:
    """Mot patch hoan chinh (tu .zip, patch.txt hoac thu mức)."""

    source: str
    min_engine_ver: Optional[str] = None
    author: Optional[str] = None
    package: Optional[str] = None
    sections: List[Section] = field(default_factory=list)
    # Tài nguyên kem theo khi nguon la .zip (tên -> noi dung bytes)
    assets: Dict[str, bytes] = field(default_factory=dict)
    # Thu mức chua tai nguyen khi nguon la thu mức / patch.txt
    asset_root: Optional[str] = None
    issues: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        base = os.path.basename(self.source)
        for suffix in (".zip", ".txt"):
            if base.lower().endswith(suffix):
                base = base[: -len(suffix)]
                break
        return base

    def section_types(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self.sections:
            counts[s.type] = counts.get(s.type, 0) + 1
        return counts
