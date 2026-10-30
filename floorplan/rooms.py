"""Group words read from a plan into rooms, and estimate a box for each."""

from __future__ import annotations

import math
import re

KINDS = ("kitchen", "bedroom", "bath", "laundry", "living", "hall", "other")

_FOOTER = re.compile(r"APPROX|SQ\.?\s*FT|^\d[\d,.\s]*$|^[0O]{1,2}$", re.I)


def _blank_features() -> dict:
    return {
        "ventilation": "none",
        "egress": "none",
        "cooktop": False,
        "open_plan": False,
        "dryer": False,
        "dryer_vented": False,
        "tub": False,
        "smoke_alarm": False,
        "anchors": {},
    }


def classify(text: str) -> str:
    folded = text.upper().replace("LAUNDY", "LAUNDRY").replace("DINNG", "DINING")
    if "KITCHEN" in folded:
        return "kitchen"
    if "LAUNDRY" in folded:
        return "laundry"
    if "BATH" in folded or re.search(r"\bWC\b", folded):
        return "bath"
    if "BED" in folded:
        return "bedroom"
    if "LIVING" in folded or "DINING" in folded:
        return "living"
    if "HALL" in folded:
        return "hall"
    return "other"


def clean_name(text: str, kind: str) -> str:
    folded = " ".join(text.upper().replace("LAUNDY", "LAUNDRY").replace("DINNG", "DINING").split())
    if kind == "kitchen" and "OPEN" in folded:
        return "Open kitchen"
    if kind == "kitchen":
        return "Kitchen"
    if kind == "laundry" and "ROOM" in folded:
        return "Laundry room"
    if kind == "laundry":
        return "Laundry closet"
    if kind == "living":
        return "Living / dining"
    if kind == "bedroom":
        return "Bedroom"
    if kind == "bath":
        return "Bath"
    if kind == "hall":
        return "Hall"
    titled = folded.title()
    return titled[:40] if titled else "Room"


def _union(tokens: list[dict], text: str | None = None) -> dict:
    x0 = min(item["x"] for item in tokens)
    y0 = min(item["y"] for item in tokens)
    x1 = max(item["x"] + item["w"] for item in tokens)
    y1 = max(item["y"] + item["h"] for item in tokens)
    joined = text if text is not None else " ".join(item["text"] for item in tokens)
    return {"text": joined, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _hgap(a: dict, b: dict) -> float:
    if a["x"] + a["w"] < b["x"]:
        return b["x"] - (a["x"] + a["w"])
    if b["x"] + b["w"] < a["x"]:
        return a["x"] - (b["x"] + b["w"])
    return 0.0


def _vgap(a: dict, b: dict) -> float:
    if a["y"] + a["h"] < b["y"]:
        return b["y"] - (a["y"] + a["h"])
    if b["y"] + b["h"] < a["y"]:
        return a["y"] - (b["y"] + b["h"])
    return 0.0


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _same_line(group: list[dict], other: dict) -> bool:
    gy = sum(item["y"] + item["h"] / 2 for item in group) / len(group)
    oy = other["y"] + other["h"] / 2
    height = max(sum(item["h"] for item in group) / len(group), other["h"])
    if abs(gy - oy) > height * 0.75:
        return False
    return min(_hgap(item, other) for item in group) < 40


def _stacked(group: list[dict], other: dict) -> bool:
    block = _union(group)
    if _vgap(block, other) > 18:
        return False
    overlap = _overlaps(block["x"], block["x"] + block["w"], other["x"], other["x"] + other["w"])
    narrower = min(block["w"], other["w"])
    return narrower > 0 and overlap / narrower > 0.35


def _cluster(tokens: list[dict], close) -> list[dict]:
    pending = sorted(tokens, key=lambda item: (item["y"], item["x"]))
    used = [False] * len(pending)
    blocks: list[dict] = []
    for index, token in enumerate(pending):
        if used[index]:
            continue
        group = [token]
        used[index] = True
        grew = True
        while grew:
            grew = False
            for other_index, other in enumerate(pending):
                if used[other_index]:
                    continue
                if close(group, other):
                    group.append(other)
                    used[other_index] = True
                    grew = True
        group.sort(key=lambda item: (item["y"], item["x"]))
        blocks.append(_union(group))
    return blocks


def _is_symbol(text: str) -> bool:
    return bool(re.fullmatch(r"[0Oo]{1,2}", text.strip()))


def _is_footer(text: str) -> bool:
    folded = text.strip()
    if _is_symbol(folded):
        return False
    return bool(_FOOTER.search(folded))


def words_to_pixels(words: list[dict], width: int, height: int) -> tuple[list[dict], list[dict]]:
    """Vision boxes use a bottom-left origin. Return room words and symbol points."""
    room_words: list[dict] = []
    symbols: list[dict] = []
    for word in words:
        if float(word.get("confidence", 1)) < 0.45:
            continue
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        x = float(word["x"]) * width
        w = float(word["w"]) * width
        h = float(word["h"]) * height
        y = (1.0 - float(word["y"]) - float(word["h"])) * height
        box = {"text": text, "x": x, "y": y, "w": w, "h": h}
        if _is_symbol(text):
            symbols.append(box)
            continue
        if _is_footer(text):
            continue
        room_words.append(box)
    return room_words, symbols


def _apply_kind_defaults(room: dict) -> None:
    kind = room["kind"]
    name = room["name"].upper()
    if kind == "kitchen":
        room["cooktop"] = True
        room["open_plan"] = "OPEN" in name
    elif kind == "laundry":
        room["dryer"] = "ROOM" not in name
    elif kind == "bedroom":
        room["egress"] = "none"


def _number_duplicates(rooms: list[dict]) -> None:
    for kind, label in (("bedroom", "Bedroom"), ("bath", "Bath")):
        group = [room for room in rooms if room["kind"] == kind and room["name"] == label]
        if len(group) < 2:
            continue
        group.sort(key=lambda room: (room["x"], room["y"]))
        for index, room in enumerate(group, start=1):
            room["name"] = f"{label} {index}"


def estimate_box(label: dict, kind: str, name: str, width: int, height: int) -> dict:
    """A starting outline around the room name. Corners can be dragged to the walls."""
    sizes = {
        "bedroom": (230, 200),
        "bath": (168, 150),
        "kitchen": (210, 230),
        "living": (260, 210),
        "hall": (220, 110),
        "other": (150, 110),
    }
    if kind == "laundry" and "ROOM" in name.upper():
        box_w, box_h = 240, 160
    elif kind == "laundry":
        box_w, box_h = 100, 120
    else:
        box_w, box_h = sizes.get(kind, (150, 110))
    cx = label["x"] + label["w"] / 2
    cy = label["y"] + label["h"] / 2
    box_w = min(box_w, width)
    box_h = min(box_h, height)
    x = min(max(0.0, cx - box_w / 2), max(0.0, width - box_w))
    y = min(max(0.0, cy - box_h / 2), max(0.0, height - box_h))
    return {"x": round(x, 1), "y": round(y, 1), "w": round(box_w, 1), "h": round(box_h, 1)}


def build_rooms(words: list[dict], symbols: list[dict], width: int, height: int) -> list[dict]:
    if not words:
        return []
    lines = _cluster(words, _same_line)
    blocks = _cluster(lines, _stacked)
    rooms: list[dict] = []
    order = sorted(blocks, key=lambda block: (block["y"], block["x"]))
    for index, block in enumerate(order, start=1):
        kind = classify(block["text"])
        if kind == "other" and len(block["text"]) < 3:
            continue
        name = clean_name(block["text"], kind)
        room = {
            "id": f"room-{index}",
            "name": name,
            "kind": kind,
            **_blank_features(),
            **estimate_box(block, kind, name, width, height),
        }
        _apply_kind_defaults(room)
        rooms.append(room)
    _number_duplicates(rooms)
    _attach_cooktops(rooms, symbols)
    return rooms


def _attach_cooktops(rooms: list[dict], symbols: list[dict]) -> None:
    kitchens = [room for room in rooms if room["kind"] == "kitchen"]
    if not kitchens or not symbols:
        return
    for symbol in symbols:
        sx = symbol["x"] + symbol["w"] / 2
        sy = symbol["y"] + symbol["h"] / 2
        nearest = min(
            kitchens,
            key=lambda room: (room["x"] + room["w"] / 2 - sx) ** 2 + (room["y"] + room["h"] / 2 - sy) ** 2,
        )
        distance = math.hypot(nearest["x"] + nearest["w"] / 2 - sx, nearest["y"] + nearest["h"] / 2 - sy)
        if distance > 220:
            continue
        nearest["cooktop"] = True
        current = (nearest.get("anchors") or {}).get("cooktop")
        if current is None or sy > current["y"]:
            nearest["anchors"]["cooktop"] = {"x": round(sx, 1), "y": round(sy, 1)}
