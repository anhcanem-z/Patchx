# -*- coding: utf-8 -*-
"""Mo hinh du lieu: Section (khối lệnh) va Patch (tệp patch)."""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
