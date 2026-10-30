"""Load a floor-plan image, trace it, and read its rooms."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from floorplan.rooms import build_rooms, words_to_pixels
from floorplan.trace import trace_ink

ROOT = Path(__file__).resolve().parents[1]
OCR_BINARY = ROOT / "bin" / "read-plan-text"
MAX_SIDE = 1600


def fit_image(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    scale = min(1.0, MAX_SIDE / max(image.size))
    if scale < 1:
        size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def trace_image(image: Image.Image) -> tuple[int, int, list[dict]]:
    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return image.width, image.height, trace_ink(gray)


def read_words(path: Path) -> list[dict]:
    if not OCR_BINARY.exists():
        return []
    completed = subprocess.run(
        [str(OCR_BINARY), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def label_texts(path: Path, width: int, height: int) -> list[str]:
    """Room-name words already printed on the drawing, for a vision prompt to confirm."""
    room_words, _symbols = words_to_pixels(read_words(path), width, height)
    return [item["text"] for item in room_words]


def read_plan(path: Path) -> dict:
    image = fit_image(Image.open(path))
    if image.size != Image.open(path).size:
        image.save(path, format="PNG")
    width, height, paths = trace_image(image)
    words = read_words(path)
    room_words, symbols = words_to_pixels(words, width, height)
    notice = ""
    if not OCR_BINARY.exists():
        notice = "Room names could not be read on this computer. Add each room yourself."
    elif not room_words:
        notice = "No room names were read. Add the kitchen, bedrooms, and baths, and the marks will follow."
    else:
        notice = "Room names were read from the drawing. Drag a corner if an outline does not sit on the walls."
    return {
        "width": width,
        "height": height,
        "paths": paths,
        "rooms": build_rooms(room_words, symbols, width, height),
        "labels": [item["text"] for item in room_words],
        "notice": notice,
    }
