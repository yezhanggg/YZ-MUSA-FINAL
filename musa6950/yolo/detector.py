"""Detector interface. Any model that turns image files into pixel boxes can plug in here.

detect_lots.py only talks to `Detector`. The YOLO backend imports ultralytics lazily, so
importing this module costs nothing and pulls in no AGPL code until a YOLO model is loaded.
To add another backend, write a class with the same `name`, `version` and `predict`, and
register it in `load_detector`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Detection:
    """One object in one image. Pixel box: left, top, right, bottom."""

    cls: str
    score: float
    left: float
    top: float
    right: float
    bottom: float


class Detector(Protocol):
    name: str
    version: str

    def predict(self, images: Sequence[Path], conf: float) -> list[list[Detection]]:
        """One list of detections per image, in the same order."""
        ...


def file_version(path: Path) -> str:
    """Short content hash of a weights file, so outputs name the exact model."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return f"{path.parent.parent.name}-{h}" if path.parent.name == "weights" else f"{path.stem}-{h}"


class YoloDetector:
    """Ultralytics YOLO weights (.pt)."""

    name = "yolo"

    def __init__(self, weights: Path, device: str = "cpu", imgsz: int = 640, batch: int = 16) -> None:
        from ultralytics import YOLO  # lazy: AGPL code loads only here

        self.model = YOLO(str(weights))
        self.device = device
        self.imgsz = imgsz
        self.batch = batch
        self.version = file_version(weights)
        self.names = self.model.names

    def predict(self, images: Sequence[Path], conf: float = 0.25) -> list[list[Detection]]:
        out: list[list[Detection]] = []
        for start in range(0, len(images), self.batch):
            chunk = [str(p) for p in images[start : start + self.batch]]
            results = self.model.predict(
                chunk, device=self.device, imgsz=self.imgsz, conf=conf, max_det=300, verbose=False
            )
            for r in results:
                boxes = r.boxes
                xyxy = boxes.xyxy.cpu().tolist()
                cls = boxes.cls.cpu().int().tolist()
                score = boxes.conf.cpu().tolist()
                out.append(
                    [
                        Detection(self.names[c], float(s), *map(float, b))
                        for b, c, s in zip(xyxy, cls, score, strict=True)
                    ]
                )
        return out


def load_detector(spec: str, device: str = "cpu") -> Detector:
    """Spec is 'backend:path', for example 'yolo:/path/to/best.pt'. A bare .pt path means YOLO."""
    backend, _, path = spec.partition(":") if ":" in spec else ("yolo", "", spec)
    if backend == "yolo":
        return YoloDetector(Path(path), device=device)
    raise ValueError(f"unknown detector backend {backend!r}")
