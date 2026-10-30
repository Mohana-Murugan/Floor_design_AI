import json

import httpx

from floorplan.vision import VISION_NOTICE, apply_reading, parse_rooms, read_rooms


def test_fenced_json_scales_fractions_to_the_sheet():
    text = """```json
{"rooms":[{"name":"Kitchen","kind":"kitchen","x":0.1,"y":0.2,"w":0.3,"h":0.25,"ventilation":"none","egress":"none","cooktop":true,"anchors":{"cooktop":{"x":0.2,"y":0.4}}}]}
```"""
    rooms = parse_rooms(text, 1000, 800)
    assert len(rooms) == 1
    room = rooms[0]
    assert room["id"] == "room-1"
    assert room["name"] == "Kitchen"
    assert room["kind"] == "kitchen"
    assert room["x"] == 100.0
    assert room["y"] == 160.0
    assert room["w"] == 300.0
    assert room["h"] == 200.0
    assert room["cooktop"] is True
    assert room["anchors"]["cooktop"] == {"x": 200.0, "y": 320.0}


def test_unknown_enums_are_dropped():
    text = json.dumps(
        {
            "rooms": [
                {
                    "name": "Garage",
                    "kind": "garage",
                    "x": 0,
                    "y": 0,
                    "w": 0.2,
                    "h": 0.2,
                    "ventilation": "skylight",
                    "egress": "skylight",
                    "cooktop": "maybe",
                    "anchors": {
                        "cooktop": {"x": 0.1, "y": 0.1},
                        "nope": {"x": 0.2, "y": 0.2},
                    },
                }
            ]
        }
    )
    room = parse_rooms(text, 1000, 800)[0]
    assert room["kind"] == "other"
    assert room["ventilation"] == "none"
    assert room["egress"] == "none"
    assert room["cooktop"] is False
    assert set(room["anchors"]) == {"cooktop"}
    assert room["anchors"]["cooktop"] == {"x": 100.0, "y": 80.0}


def test_box_is_clamped_to_the_sheet():
    text = json.dumps(
        {"rooms": [{"name": "Hall", "kind": "hall", "x": 0.9, "y": -0.2, "w": 0.5, "h": 0.1}]}
    )
    room = parse_rooms(text, 1000, 800)[0]
    assert room["y"] == 0.0
    assert room["x"] + room["w"] <= 1000
    assert room["w"] >= 8


def test_empty_or_fenced_json_yields_no_rooms():
    assert parse_rooms("", 100, 100) == []
    assert parse_rooms('```json\n{"rooms": []}\n```', 100, 100) == []
    assert parse_rooms("not json", 100, 100) == []
    assert parse_rooms('{"note": "no rooms key"}', 100, 100) == []


def test_empty_reading_keeps_the_ocr_rooms():
    kept = apply_reading(
        {"rooms": [{"id": "ocr"}], "notice": "Room names were read from the drawing."},
        None,
    )
    assert kept["rooms"] == [{"id": "ocr"}]
    assert kept["notice"].startswith("Room names")
    still = apply_reading(
        {"rooms": [{"id": "ocr"}], "notice": "Room names were read from the drawing."},
        [],
    )
    assert still["rooms"] == [{"id": "ocr"}]
    updated = apply_reading({"rooms": [], "notice": ""}, [{"id": "room-1"}])
    assert updated["rooms"] == [{"id": "room-1"}]
    assert updated["notice"] == VISION_NOTICE


def test_missing_key_skips_the_network(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("floorplan.vision.request_completion", boom)
    assert read_rooms(b"png", 100, 100, []) is None


def test_request_error_returns_none(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("floorplan.vision.request_completion", boom)
    assert read_rooms(b"png", 100, 100, []) is None


def test_unusable_reply_returns_no_rooms(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr("floorplan.vision.request_completion", lambda *_args, **_kwargs: "hello")
    assert read_rooms(b"png", 100, 100, []) == []
