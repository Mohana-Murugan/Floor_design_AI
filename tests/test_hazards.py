from floorplan.hazards import analyze
from floorplan.sample_plan import sample_rooms


def test_open_kitchen_without_ventilation_is_the_lead_finding():
    incidents = analyze(sample_rooms())
    kitchen = next(item for item in incidents if item["id"] == "kitchen:cooktop-vent")
    assert kitchen["severity"] == "high"
    assert "no ventilation" in kitchen["title"].lower()
    assert kitchen["suggestion"].lower().startswith("provide ventilation")
    assert incidents[0]["id"] == "kitchen:cooktop-vent"


def test_range_hood_clears_the_cooking_fire():
    rooms = sample_rooms()
    kitchen = next(room for room in rooms if room["id"] == "kitchen")
    kitchen["ventilation"] = "range_hood"
    ids = {item["id"] for item in analyze(rooms)}
    assert "kitchen:cooktop-vent" not in ids


def test_window_keeps_a_weaker_hood_warning():
    rooms = sample_rooms()
    kitchen = next(room for room in rooms if room["id"] == "kitchen")
    kitchen["ventilation"] = "window"
    kitchen_hit = next(item for item in analyze(rooms) if item["room_id"] == "kitchen")
    assert kitchen_hit["severity"] == "medium"
    assert "hood" in kitchen_hit["suggestion"].lower()


def test_marking_the_dryer_vent_clears_the_closet():
    rooms = sample_rooms()
    closet = next(room for room in rooms if room["id"] == "laundry-closet")
    closet["dryer_vented"] = True
    ids = {item["id"] for item in analyze(rooms)}
    assert "laundry-closet:dryer" not in ids


def test_sample_covers_the_drawn_risks():
    incidents = analyze(sample_rooms())
    titles = {item["title"] for item in incidents}
    assert "Only one way out" in titles
    assert "Dryer fire — no ventilation" in titles
    assert "No second way out" in titles
    assert "No smoke alarm outside the bedrooms" in titles
    assert any(item["room_id"] == "bath-e" and "tub" in item["title"].lower() for item in incidents)
    assert sum(1 for item in incidents if item["severity"] == "high") >= 6
