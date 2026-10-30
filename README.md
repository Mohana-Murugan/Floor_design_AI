# Floor incident marks

Upload a floor plan and it becomes an editable drawing. Likely incidents are pinned on the plan, each with a reason and a fix. A kitchen cooktop with no hood, fan, or window is marked as a cooking fire, and the suggestion is to provide ventilation.

## Run

```bash
uv run python main.py
```

Open http://127.0.0.1:8000

The included plan (about 1,290 sq ft) loads on its own. Upload a PNG or JPG to read the room names from that drawing. Drag a room to move it, drag a corner to resize it, and change ventilation, the way out, a dryer, or a smoke alarm — the marks update.

Export SVG keeps the drawing, the marks, and the room settings. Upload that SVG here to keep editing.

## Read the drawing

Set `XAI_API_KEY` to have Grok propose rooms and fixtures when you upload a plan, or when you press Read drawing. It looks for a cooktop, a hood, a fan, a window, a dryer, a tub, a door, and a smoke alarm, and it fills the same room settings the editor already uses. Optional: `XAI_VISION_MODEL` (default `grok-4.7`).

Without the key, upload still reads room names from the labels on the drawing. A failed read leaves those rooms in place.

These marks follow what was read. They are not a building-code inspection.
