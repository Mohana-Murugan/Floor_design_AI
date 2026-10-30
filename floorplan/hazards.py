"""Rules that turn room settings into likely incidents and a suggested fix.

Marks follow what is recorded on each room. A kitchen with a cooktop and no
ventilation is the central case: a cooking fire is likely, and the fix is to
provide ventilation.
"""

from __future__ import annotations

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _pin(room: dict, key: str, fx: float, fy: float) -> tuple[float, float]:
    anchor = (room.get("anchors") or {}).get(key)
    if anchor:
        return float(anchor["x"]), float(anchor["y"])
    return float(room["x"]) + float(room["w"]) * fx, float(room["y"]) + float(room["h"]) * fy


def _incident(
    room: dict,
    suffix: str,
    severity: str,
    priority: int,
    title: str,
    why: str,
    suggestion: str,
    pin_key: str,
    fx: float,
    fy: float,
) -> dict:
    x, y = _pin(room, pin_key, fx, fy)
    return {
        "id": f"{room['id']}:{suffix}",
        "room_id": room["id"],
        "severity": severity,
        "priority": priority,
        "title": title,
        "why": why,
        "suggestion": suggestion,
        "place": room.get("name") or "Plan",
        "x": round(x, 1),
        "y": round(y, 1),
    }


def _spread(incidents: list[dict]) -> list[dict]:
    placed: list[tuple[float, float]] = []
    for incident in incidents:
        x, y = float(incident["x"]), float(incident["y"])
        guard = 0
        while any(abs(x - ox) < 28 and abs(y - oy) < 28 for ox, oy in placed) and guard < 6:
            y += 30
            guard += 1
        incident["x"], incident["y"] = round(x, 1), round(y, 1)
        placed.append((x, y))
    return incidents


def _kitchen(room: dict) -> list[dict]:
    if not room.get("cooktop"):
        return []
    ventilation = room.get("ventilation") or "none"
    open_plan = bool(room.get("open_plan"))
    if ventilation == "none":
        why = (
            "A cooktop is drawn here and no hood, fan, or window is shown. "
            "Heat and smoke from a pan fire stay in the room."
        )
        suggestion = (
            "Provide ventilation. Install a range hood over the cooktop and duct it to the outside. "
            "Keep a fire extinguisher beside the stove, not above it."
        )
        if open_plan:
            why += " The kitchen is open, so smoke moves straight into the living space and the path people use to leave."
            suggestion += (
                " Because the kitchen is open to the living room, the hood has to exhaust outside, "
                "not only recirculate. Put a smoke alarm on the living side of the opening, "
                "and keep the walk past the stove clear."
            )
        return [
            _incident(
                room,
                "cooktop-vent",
                "high",
                0,
                "Cooking fire — no ventilation",
                why,
                suggestion,
                "cooktop",
                0.32,
                0.82,
            )
        ]
    if ventilation == "range_hood":
        return []
    return [
        _incident(
            room,
            "cooktop-vent",
            "medium",
            0,
            "Cooktop still needs a hood",
            "A window or a fan is marked, but there is no range hood over the cooktop. "
            "Grease and smoke from a fire will not all leave through a distant opening.",
            "Provide a range hood ducted to the outside, directly over the cooktop.",
            "cooktop",
            0.32,
            0.82,
        )
    ]


def _bedroom(room: dict) -> list[dict]:
    found: list[dict] = []
    if (room.get("egress") or "none") == "none":
        alarm = ""
        if not room.get("smoke_alarm"):
            alarm = " Put a smoke alarm inside this bedroom and keep the path to the window clear."
        found.append(
            _incident(
                room,
                "egress",
                "high",
                2,
                "No second way out",
                "No egress window or outside door is drawn for this bedroom. "
                "If the hall fills with smoke, there is no other way out.",
                "Provide an egress window large enough to climb through, with a sill a person can reach."
                + alarm,
                "egress",
                0.72,
                0.72,
            )
        )
    elif not room.get("smoke_alarm"):
        found.append(
            _incident(
                room,
                "alarm",
                "medium",
                6,
                "No smoke alarm in this bedroom",
                "This bedroom has a way out drawn, and no smoke alarm is marked inside it.",
                "Put a smoke alarm inside this bedroom, interconnected with the alarm in the hall.",
                "alarm",
                0.28,
                0.3,
            )
        )
    return found


def _bath(room: dict) -> list[dict]:
    needs_fan = (room.get("ventilation") or "none") == "none"
    has_tub = bool(room.get("tub"))
    if needs_fan and has_tub:
        return [
            _incident(
                room,
                "bath",
                "medium",
                5,
                "No fan, and the tub is a fall risk",
                "No window or exhaust fan is drawn, so moisture stays in the room. "
                "A tub is drawn with no grab bar or slip-resistant base.",
                "Provide an exhaust fan ducted to the outside. Add a slip-resistant tub floor and a grab bar, "
                "and limit how hot the shower can get.",
                "tub",
                0.72,
                0.48,
            )
        ]
    if needs_fan:
        return [
            _incident(
                room,
                "bath",
                "medium",
                5,
                "Bathroom has no ventilation",
                "No window or exhaust fan is drawn. Moisture stays in the room, which makes mold and a slippery floor more likely.",
                "Provide an exhaust fan ducted to the outside.",
                "fan",
                0.46,
                0.55,
            )
        ]
    if has_tub:
        return [
            _incident(
                room,
                "bath",
                "medium",
                5,
                "Slip and scald at the tub",
                "A tub is drawn, with no grab bar or slip-resistant base shown.",
                "Add a slip-resistant tub floor and a grab bar, and limit how hot the shower can get.",
                "tub",
                0.72,
                0.48,
            )
        ]
    return []


def _laundry(room: dict) -> list[dict]:
    if not room.get("dryer") or room.get("dryer_vented"):
        return []
    on_exterior = (room.get("egress") or "none") == "exterior_door"
    if on_exterior:
        why = (
            "A dryer is marked in this room and no duct to the outside is drawn. "
            "Lint and heat with nowhere to go are a common way a dryer fire starts."
        )
        suggestion = (
            "Vent the dryer to the outside with a short, smooth metal duct. "
            "Keep clothes and baskets away from the appliance, and do not let them block the door."
        )
    else:
        why = (
            "This laundry sits inside the plan, with no exterior wall drawn for a duct. "
            "A dryer here would hold heat and lint in a closed closet, which is a common way a fire starts."
        )
        suggestion = (
            "Provide a vent to the outside: a short, smooth metal dryer duct. "
            "If you cannot run that duct, do not put a dryer in this closet. "
            "Use a laundry room on an exterior wall, and do not store clothes against the appliance."
        )
    return [
        _incident(
            room,
            "dryer",
            "high",
            4,
            "Dryer fire — no ventilation",
            why,
            suggestion,
            "dryer",
            0.5,
            0.62,
        )
    ]


def _single_exit(rooms: list[dict]) -> list[dict]:
    bedrooms = [room for room in rooms if room.get("kind") == "bedroom"]
    if not bedrooms:
        return []
    doors = [room for room in rooms if (room.get("egress") or "none") == "exterior_door"]
    if len(doors) > 1:
        return []
    if len(doors) == 1:
        room = doors[0]
        if room.get("kind") == "laundry":
            why = (
                "The only exterior door on the drawing is in the laundry room. "
                "Every bedroom reaches it by passing the kitchen. "
                "A basket, a leak, or a fire at the stove can block that door."
            )
            suggestion = (
                "Confirm a second exit, and give each bedroom its own egress window. "
                "Keep this door and its swing clear. If the washer is in this room, "
                "set it in a pan with a shutoff you can reach."
            )
        else:
            why = (
                f"The only exterior door on the drawing is in {room.get('name', 'this room')}. "
                "If it is blocked, no other door is shown."
            )
            suggestion = (
                "Confirm a second exit. Keep this door and its swing clear, "
                "and give each bedroom an egress window of its own."
            )
        return [
            _incident(
                room,
                "single-exit",
                "high",
                1,
                "Only one way out",
                why,
                suggestion,
                "door",
                0.22,
                0.84,
            )
        ]

    xs = [float(room["x"]) + float(room["w"]) / 2 for room in bedrooms]
    ys = [float(room["y"]) + float(room["h"]) / 2 for room in bedrooms]
    return [
        {
            "id": "plan:no-exit",
            "room_id": "plan",
            "severity": "high",
            "priority": 1,
            "title": "No way out is drawn",
            "why": (
                "No exterior door is marked, and the plan has bedrooms. "
                "The drawing may simply have left the door off."
            ),
            "suggestion": (
                "Mark Exterior door on the room that has it. "
                "If the home really has only one entry, confirm a second way out "
                "and an egress window in each bedroom."
            ),
            "place": "Whole plan",
            "x": round(sum(xs) / len(xs), 1),
            "y": round(sum(ys) / len(ys), 1),
        }
    ]


def _hall_alarm(rooms: list[dict]) -> list[dict]:
    bedrooms = [room for room in rooms if room.get("kind") == "bedroom"]
    if not bedrooms:
        return []
    halls = [room for room in rooms if room.get("kind") == "hall"]
    if any(room.get("smoke_alarm") for room in halls):
        return []
    if halls:
        room = halls[0]
        return [
            _incident(
                room,
                "hall-alarm",
                "high",
                3,
                "No smoke alarm outside the bedrooms",
                "Nothing on the drawing shows an alarm in the hall, which is the path from every bedroom toward the door.",
                "Install an interconnected smoke alarm in this hall. "
                "If the cooktop or the dryer is gas, add a carbon monoxide alarm here as well.",
                "alarm",
                0.5,
                0.5,
            )
        ]
    xs = [float(room["x"]) + float(room["w"]) / 2 for room in bedrooms]
    ys = [float(room["y"]) + float(room["h"]) * 0.92 for room in bedrooms]
    return [
        {
            "id": "plan:hall-alarm",
            "room_id": "plan",
            "severity": "high",
            "priority": 3,
            "title": "No smoke alarm outside the bedrooms",
            "why": "Bedrooms are marked, and no hall alarm is marked on the way out.",
            "suggestion": (
                "Add the hall if it is missing, and install an interconnected smoke alarm there. "
                "If the cooktop or the dryer is gas, add a carbon monoxide alarm in that same spot."
            ),
            "place": "Outside the bedrooms",
            "x": round(sum(xs) / len(xs), 1),
            "y": round(sum(ys) / len(ys), 1),
        }
    ]


def _normalize(room: dict) -> dict:
    kind = room.get("kind")
    if kind not in {"kitchen", "bedroom", "bath", "laundry", "living", "hall", "other"}:
        kind = "other"
    ventilation = room.get("ventilation")
    if ventilation not in {"none", "window", "exhaust_fan", "range_hood"}:
        ventilation = "none"
    egress = room.get("egress")
    if egress not in {"none", "window", "exterior_door"}:
        egress = "none"

    def num(key: str, default: float = 0) -> float:
        try:
            return float(room.get(key, default))
        except (TypeError, ValueError):
            return default

    anchors = {}
    raw_anchors = room.get("anchors")
    if isinstance(raw_anchors, dict):
        for key, value in raw_anchors.items():
            if isinstance(value, dict):
                try:
                    anchors[str(key)] = {"x": float(value["x"]), "y": float(value["y"])}
                except (TypeError, ValueError, KeyError):
                    continue
    return {
        "id": str(room.get("id") or "room"),
        "name": str(room.get("name") or "Room")[:80],
        "kind": kind,
        "x": num("x"),
        "y": num("y"),
        "w": max(8.0, num("w", 40)),
        "h": max(8.0, num("h", 40)),
        "ventilation": ventilation,
        "egress": egress,
        "cooktop": bool(room.get("cooktop")),
        "open_plan": bool(room.get("open_plan")),
        "dryer": bool(room.get("dryer")),
        "dryer_vented": bool(room.get("dryer_vented")),
        "tub": bool(room.get("tub")),
        "smoke_alarm": bool(room.get("smoke_alarm")),
        "anchors": anchors,
    }


def analyze(rooms: list[dict]) -> list[dict]:
    rooms = [_normalize(room) for room in rooms]
    incidents: list[dict] = []
    for room in rooms:
        kind = room.get("kind")
        if kind == "kitchen":
            incidents.extend(_kitchen(room))
        elif kind == "bedroom":
            incidents.extend(_bedroom(room))
        elif kind == "bath":
            incidents.extend(_bath(room))
        elif kind == "laundry":
            incidents.extend(_laundry(room))
    incidents.extend(_single_exit(rooms))
    incidents.extend(_hall_alarm(rooms))
    incidents.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["priority"], item["y"], item["x"]))
    return _spread(incidents)
