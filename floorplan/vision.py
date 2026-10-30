"""Ask Grok to read rooms and fixtures from a floor-plan image.

The model fills the same room records the editor already edits. Incident
marks stay in the rules: a fixture that is not clearly drawn stays off.
"""

from __future__ import annotations

import base64
import json
import os
import re

import httpx

from floorplan.hazards import _normalize

API_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4.7"
TIMEOUT_SECONDS = 60.0
VISION_NOTICE = (
    "Rooms and fixtures were read from the drawing. "
    "Change anything that does not match, and the marks follow."
)

_KINDS = {"kitchen", "bedroom", "bath", "laundry", "living", "hall", "other"}
_VENTILATION = {"none", "window", "exhaust_fan", "range_hood"}
_EGRESS = {"none", "window", "exterior_door"}
_ANCHORS = {"cooktop", "dryer", "tub", "door", "alarm", "fan", "egress"}
_TRUE = {"true", "yes", "1"}

_SYSTEM = (
    "You read floor plans. Reply with JSON only. "
    "Mark a fixture only when its symbol is visible on the drawing. "
    "If you are unsure, use none or false. "
    "Do not write incident titles or advice."
)

_USER = """\
Return one JSON object with a rooms array. Each room has:
- name
- kind: kitchen, bedroom, bath, laundry, living, hall, or other
- x, y, w, h as fractions of the image width and height, origin at the top-left
- ventilation: none, window, exhaust_fan, or range_hood
- egress: none, window, or exterior_door
- cooktop, open_plan, dryer, dryer_vented, tub, smoke_alarm as booleans
- optional anchors, each {x, y} in the same fraction space, for cooktop, dryer, tub, door, alarm, fan, or egress

A range hood counts only when a hood is drawn over the cooktop.
An exterior door counts only when a door to the outside is drawn.
A smoke alarm counts only when an alarm symbol is drawn in that room.
"""


def apply_reading(plan: dict, rooms: list[dict] | None) -> dict:
    """Use vision rooms when the read produced any. Otherwise leave the plan as it is."""
    if rooms:
        plan["rooms"] = rooms
        plan["notice"] = VISION_NOTICE
    return plan


def read_rooms(
    image_png: bytes,
    width: int,
    height: int,
    hints: list[str] | None = None,
) -> list[dict] | None:
    """Read rooms from a PNG. None when no key is set or the request fails."""
    if not os.environ.get("XAI_API_KEY", "").strip():
        return None
    try:
        text = request_completion(image_png, hints or [])
    except Exception:
        return None
    return parse_rooms(text, width, height)


def request_completion(image_png: bytes, hints: list[str]) -> str:
    key = os.environ["XAI_API_KEY"].strip()
    model = os.environ.get("XAI_VISION_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    encoded = base64.standard_b64encode(image_png).decode("ascii")
    body = {
        "model": model,
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": _USER + _hint_block(hints)},
                ],
            },
        ],
    }
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        response = client.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
    message = payload["choices"][0]["message"]
    content = message.get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return str(content or "")


def parse_rooms(text: str, width: int, height: int) -> list[dict]:
    """Turn model text into room records. Empty or unusable text returns no rooms."""
    if width < 8 or height < 8:
        return []
    raw_rooms = _room_dicts(_extract_json(text))
    rooms: list[dict] = []
    for index, raw in enumerate(raw_rooms, start=1):
        rooms.append(_one_room(raw, index, width, height))
    return rooms


def _hint_block(hints: list[str]) -> str:
    lines: list[str] = []
    for hint in hints:
        text = " ".join(str(hint).split())
        if not text:
            continue
        lines.append(f"- {text[:80]}")
        if len(lines) == 40:
            break
    if not lines:
        return ""
    return (
        "\nLabels already read from the drawing, for you to confirm. They are not fixtures:\n"
        + "\n".join(lines)
    )


def _extract_json(text: str) -> object | None:
    stripped = text.strip()
    if not stripped:
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S | re.I)
    if fence:
        stripped = fence.group(1).strip()
    for candidate in (stripped, _span(stripped, "{", "}"), _span(stripped, "[", "]")):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _span(text: str, open_char: str, close_char: str) -> str:
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1]


def _room_dicts(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("rooms")
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _one_room(raw: dict, index: int, width: int, height: int) -> dict:
    kind = raw.get("kind")
    ventilation = raw.get("ventilation")
    egress = raw.get("egress")
    anchors: dict[str, dict[str, float]] = {}
    raw_anchors = raw.get("anchors")
    if isinstance(raw_anchors, dict):
        for key, value in raw_anchors.items():
            if key not in _ANCHORS:
                continue
            point = _point(value, width, height)
            if point is not None:
                anchors[key] = point
    room = {
        "id": f"room-{index}",
        "name": raw.get("name") or "Room",
        "kind": kind if kind in _KINDS else "other",
        **_box(raw, width, height),
        "ventilation": ventilation if ventilation in _VENTILATION else "none",
        "egress": egress if egress in _EGRESS else "none",
        "cooktop": _flag(raw.get("cooktop")),
        "open_plan": _flag(raw.get("open_plan")),
        "dryer": _flag(raw.get("dryer")),
        "dryer_vented": _flag(raw.get("dryer_vented")),
        "tub": _flag(raw.get("tub")),
        "smoke_alarm": _flag(raw.get("smoke_alarm")),
        "anchors": anchors,
    }
    return _normalize(room)


def _box(raw: dict, width: int, height: int) -> dict[str, float]:
    x = (_fraction(raw.get("x")) or 0.0) * width
    y = (_fraction(raw.get("y")) or 0.0) * height
    w_frac = _fraction(raw.get("w"))
    h_frac = _fraction(raw.get("h"))
    w = (w_frac if w_frac else 40.0 / width) * width
    h = (h_frac if h_frac else 40.0 / height) * height
    x = min(max(0.0, x), max(0.0, width - 8.0))
    y = min(max(0.0, y), max(0.0, height - 8.0))
    w = min(max(8.0, w), width - x)
    h = min(max(8.0, h), height - y)
    return {"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1)}


def _point(value: object, width: int, height: int) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    x = _fraction(value.get("x"))
    y = _fraction(value.get("y"))
    if x is None or y is None:
        return None
    return {"x": round(x * width, 1), "y": round(y * height, 1)}


def _fraction(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return min(1.0, max(0.0, number))


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return False
