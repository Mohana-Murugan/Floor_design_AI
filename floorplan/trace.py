"""Turn a black-line floor plan into filled SVG paths."""

from __future__ import annotations

import cv2
import numpy as np


def _epsilon(area: float) -> float:
    if area < 80:
        return 0.45
    if area < 500:
        return 0.75
    return 1.15


def _path(contour: np.ndarray) -> str:
    points = contour[:, 0, :]
    commands = [f"M{points[0][0]:.1f} {points[0][1]:.1f}"]
    commands.extend(f"L{x:.1f} {y:.1f}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def _children(hierarchy: np.ndarray, index: int) -> list[int]:
    child = int(hierarchy[index][2])
    kids: list[int] = []
    while child != -1:
        kids.append(child)
        child = int(hierarchy[child][0])
    return kids


def _simplify(contour: np.ndarray) -> str | None:
    area = float(cv2.contourArea(contour))
    if area < 3:
        return None
    simplified = cv2.approxPolyDP(contour, _epsilon(area), True)
    if len(simplified) < 3:
        return None
    return _path(simplified)


def trace_ink(gray: np.ndarray) -> list[dict]:
    """Filled wall shapes with transparent holes, so a photo can sit behind the lines."""
    ink = (gray < 175).astype(np.uint8) * 255
    contours, hierarchy = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    paths: list[dict] = []

    def emit(index: int) -> None:
        parts: list[str] = []
        nested: list[int] = []
        own = _simplify(contours[index])
        if own:
            parts.append(own)
        for hole in _children(hierarchy, index):
            opening = _simplify(contours[hole])
            if opening:
                parts.append(opening)
            nested.extend(_children(hierarchy, hole))
        if parts:
            paths.append({"d": " ".join(parts), "ink": True})
        for grandchild in nested:
            emit(grandchild)

    for index in range(len(contours)):
        if int(hierarchy[index][3]) == -1:
            emit(index)
    return paths
