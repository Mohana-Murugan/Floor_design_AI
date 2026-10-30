"""Local editor: upload a floor plan, trace it, and mark likely incidents."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from floorplan.hazards import analyze
from floorplan.read_plan import OCR_BINARY, ROOT, fit_image, label_texts, read_plan, trace_image
from floorplan.sample_plan import sample_rooms
from floorplan.vision import VISION_NOTICE, apply_reading, read_rooms

SAMPLE_PATH = ROOT / "samples" / "floor-plan.png"
UPLOADS = ROOT / "uploads"
MAX_BYTES = 15 * 1024 * 1024

UPLOADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Floor incident marks")
_sample: dict | None = None


def _ensure_ocr() -> None:
    if OCR_BINARY.exists() or platform.system() != "Darwin":
        return
    source = ROOT / "ocr" / "read-plan-text.swift"
    if not source.exists():
        return
    OCR_BINARY.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-O", "-o", str(OCR_BINARY), str(source)], check=False)


def _load_sample() -> dict:
    global _sample
    if _sample is None:
        image = fit_image(Image.open(SAMPLE_PATH))
        width, height, paths = trace_image(image)
        _sample = {
            "width": width,
            "height": height,
            "paths": paths,
            "rooms": sample_rooms(),
            "image_url": "/samples/floor-plan.png",
            "name": "Sample plan, about 1,290 sq ft",
            "notice": "",
            "custom": [],
            "dismissed": [],
            "pinOverrides": {},
        }
    return _sample


def _looks_like_svg(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<svg") or head.startswith(b"<?xml") or b"<svg" in head


def _read_exported(svg_text: str) -> dict | None:
    match = re.search(
        r'<metadata id="floor-incident-state"><!\[CDATA\[(.*?)\]\]></metadata>',
        svg_text,
        re.S,
    )
    if not match:
        return None
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict) or "rooms" not in state or "width" not in state:
        return None
    return state


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _fitted_png(path: Path) -> tuple[bytes, int, int]:
    with Image.open(path) as opened:
        image = fit_image(opened)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), image.width, image.height


def _labels_for(path: Path, png: bytes, width: int, height: int) -> list[str]:
    with Image.open(path) as opened:
        same_size = opened.size == (width, height)
    if same_size:
        return label_texts(path, width, height)
    handle, name = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    temporary = Path(name)
    try:
        temporary.write_bytes(png)
        return label_texts(temporary, width, height)
    finally:
        temporary.unlink(missing_ok=True)


def _local_image(url: object) -> Path | None:
    if not isinstance(url, str) or not url.startswith("/"):
        return None
    parts = [part for part in url.split("/") if part]
    if len(parts) != 2:
        return None
    root_name, name = parts
    if root_name == "uploads":
        root = UPLOADS
    elif root_name == "samples":
        root = ROOT / "samples"
    else:
        return None
    if name != Path(name).name or Path(name).suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    path = (root / name).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


_ensure_ocr()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/sample")
def sample() -> dict:
    if not SAMPLE_PATH.exists():
        raise HTTPException(404, "The sample plan is missing.")
    return _load_sample()


@app.post("/api/analyze")
def analyze_rooms(payload: dict) -> list[dict]:
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms, list):
        raise HTTPException(400, "Expected a list of rooms.")
    return analyze(rooms)


@app.post("/api/plan")
async def upload_plan(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "That file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "That file is larger than 15 MB.")
    if _looks_like_svg(data):
        restored = _read_exported(data.decode("utf-8", "ignore"))
        if restored is None:
            raise HTTPException(
                400,
                "This SVG was not exported from this review. Upload a PNG or JPG of the plan.",
            )
        restored["restored"] = True
        restored["image_url"] = restored.get("image_url") or ""
        restored["notice"] = "Opened an exported drawing. Room settings and marks are as you saved them."
        restored["name"] = file.filename or restored.get("name") or "Exported plan"
        return restored

    try:
        image = fit_image(Image.open(BytesIO(data)))
    except UnidentifiedImageError as error:
        raise HTTPException(400, "That file is not a floor-plan image.") from error

    UPLOADS.mkdir(parents=True, exist_ok=True)
    destination = UPLOADS / f"{uuid.uuid4().hex}.png"
    image.save(destination, format="PNG")
    plan = read_plan(destination)
    labels = plan.pop("labels", [])
    seen = read_rooms(
        destination.read_bytes(),
        int(plan["width"]),
        int(plan["height"]),
        labels if isinstance(labels, list) else [],
    )
    apply_reading(plan, seen)
    plan["image_url"] = f"/uploads/{destination.name}"
    plan["name"] = file.filename or "Uploaded plan"
    plan["custom"] = []
    plan["dismissed"] = []
    plan["pinOverrides"] = {}
    return plan


@app.post("/api/read")
def read_drawing(payload: dict) -> dict:
    url = payload.get("image_url") if isinstance(payload, dict) else None
    path = _local_image(url)
    if path is None:
        raise HTTPException(400, "That drawing is not on this computer.")
    if not os.environ.get("XAI_API_KEY", "").strip():
        raise HTTPException(503, "Set XAI_API_KEY to read fixtures from the drawing.")
    png, width, height = _fitted_png(path)
    rooms = read_rooms(png, width, height, _labels_for(path, png, width, height))
    if not rooms:
        raise HTTPException(
            502,
            "The drawing could not be read. The rooms already on the plan are unchanged.",
        )
    return {"rooms": rooms, "notice": VISION_NOTICE}


app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
