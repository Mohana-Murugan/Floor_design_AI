const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  width: 1024,
  height: 682,
  paths: [],
  rooms: [],
  imageUrl: "",
  name: "",
  notice: "",
  ruleIncidents: [],
  custom: [],
  dismissed: {},
  pinOverrides: {},
  selectedId: null,
  selectedRoomId: null,
  mode: "select",
  showDrawing: true,
  showPhoto: false,
  showRooms: true,
  visible: [],
};

const cam = { x: 0, y: 0, w: 1024, h: 682 };
let ticket = 0;
let customSerial = 1;
let drag = null;

const svg = document.getElementById("plan");
const hint = document.getElementById("hint");
const roomsPanel = document.getElementById("rooms");
const findingsPanel = document.getElementById("findings");

const KIND_LABELS = {
  kitchen: "Kitchen",
  bedroom: "Bedroom",
  bath: "Bath",
  laundry: "Laundry",
  living: "Living",
  hall: "Hall",
  other: "Other",
};

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "checked" || key === "hidden") node[key] = Boolean(value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value != null && value !== false) node.setAttribute(key, String(value));
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function screenUnits(pixels) {
  const matrix = svg.getScreenCTM();
  if (!matrix || Math.abs(matrix.a) < 0.0001) return pixels;
  return pixels / matrix.a;
}

function clientToPlan(clientX, clientY) {
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  const matrix = svg.getScreenCTM();
  if (!matrix) return { x: 0, y: 0 };
  const mapped = point.matrixTransform(matrix.inverse());
  return { x: mapped.x, y: mapped.y };
}

function applyCam() {
  svg.setAttribute("viewBox", `${cam.x} ${cam.y} ${cam.w} ${cam.h}`);
}

function setHint(text, isError = false) {
  hint.textContent = text;
  hint.classList.toggle("error", isError);
}

function modeHint() {
  if (state.mode === "add-room") return "Drag a rectangle around the room.";
  if (state.mode === "add-mark") return "Click the place you want to mark.";
  return "Drag a room to move it, a corner to resize it, or a mark to place it. Drag empty paper to pan.";
}

function showHint() {
  const parts = [];
  if (state.notice) parts.push(state.notice);
  parts.push(modeHint());
  setHint(parts.join(" "));
}

function blankRoom(partial) {
  return {
    ventilation: "none",
    egress: "none",
    cooktop: false,
    open_plan: false,
    dryer: false,
    dryer_vented: false,
    tub: false,
    smoke_alarm: false,
    anchors: {},
    ...partial,
  };
}

function visibleIncidents() {
  const rules = state.ruleIncidents
    .filter((item) => !state.dismissed[item.id])
    .map((item) => {
      const moved = state.pinOverrides[item.id];
      return moved ? { ...item, x: moved.x, y: moved.y } : { ...item };
    });
  const custom = state.custom.map((item) => ({ ...item, custom: true }));
  const items = [...rules, ...custom];
  const rank = { high: 0, medium: 1, low: 2 };
  items.sort(
    (a, b) =>
      (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3) ||
      (a.priority ?? 9) - (b.priority ?? 9) ||
      a.y - b.y,
  );
  items.forEach((item, index) => {
    item.number = index + 1;
  });
  state.visible = items;
  return items;
}

function placeName(incident) {
  const room = state.rooms.find((item) => item.id === incident.room_id);
  return room ? room.name : incident.place || "Plan";
}

function roomAt(point) {
  const hits = state.rooms.filter(
    (room) => point.x >= room.x && point.x <= room.x + room.w && point.y >= room.y && point.y <= room.y + room.h,
  );
  hits.sort((a, b) => a.w * a.h - b.w * b.h);
  return hits[0] || null;
}

function selectIncident(id) {
  state.selectedId = id;
  const incident = state.visible.find((item) => item.id === id);
  if (incident && incident.room_id !== "plan") state.selectedRoomId = incident.room_id;
  renderAnnotations();
  renderFindings();
  renderRoomList();
}

async function analyze() {
  const mine = ++ticket;
  let payload = [];
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms: state.rooms }),
    });
    if (!response.ok) throw new Error("The incident check failed.");
    payload = await response.json();
  } catch (error) {
    if (mine !== ticket) return;
    setHint(error.message || "The incident check failed.", true);
    return;
  }
  if (mine !== ticket) return;
  state.ruleIncidents = payload;
  const items = visibleIncidents();
  if (!items.some((item) => item.id === state.selectedId)) {
    state.selectedId = items[0]?.id || null;
    const picked = items.find((item) => item.id === state.selectedId);
    if (picked && picked.room_id !== "plan") state.selectedRoomId = picked.room_id;
  }
  renderAnnotations();
  renderFindings();
  const scroll = roomsPanel.scrollTop;
  renderRoomList();
  roomsPanel.scrollTop = scroll;
  showHint();
}

function ensureSvg() {
  svg.replaceChildren();
  svg.append(el("rect", { id: "sheet", fill: "#fbf8f3" }));
  svg.append(el("image", { id: "photo", preserveAspectRatio: "none" }));
  svg.append(el("g", { id: "drawing" }));
  svg.append(el("g", { id: "rooms" }));
  svg.append(el("g", { id: "pins" }));
}

function renderPaths() {
  const sheet = svg.querySelector("#sheet");
  sheet.setAttribute("width", state.width);
  sheet.setAttribute("height", state.height);
  const photo = svg.querySelector("#photo");
  if (state.showPhoto && state.imageUrl) {
    photo.setAttribute("href", state.imageUrl);
    photo.setAttribute("width", state.width);
    photo.setAttribute("height", state.height);
    photo.setAttribute("opacity", state.showDrawing ? "0.28" : "1");
  } else {
    photo.removeAttribute("href");
  }
  const drawing = svg.querySelector("#drawing");
  drawing.replaceChildren();
  if (!state.showDrawing) return;
  for (const path of state.paths) {
    drawing.append(el("path", { d: path.d, fill: "#1c1915", "fill-rule": "evenodd" }));
  }
}

function renderAnnotations() {
  const rooms = svg.querySelector("#rooms");
  const pins = svg.querySelector("#pins");
  rooms.replaceChildren();
  pins.replaceChildren();
  const unit = screenUnits(1);
  if (state.showRooms) {
    for (const room of state.rooms) {
      const selected = room.id === state.selectedRoomId;
      const group = el("g", { "data-room": room.id });
      group.append(
        el("rect", {
          class: selected ? "room-shape selected" : "room-shape",
          x: room.x,
          y: room.y,
          width: room.w,
          height: room.h,
        }),
      );
      const label = el("text", {
        class: "room-label",
        x: room.x + 8 * unit,
        y: room.y + 16 * unit,
        "font-size": 13 * unit,
      });
      label.textContent = room.name;
      group.append(label);
      if (selected) {
        const size = 8 * unit;
        for (const corner of ["nw", "ne", "se", "sw"]) {
          const [hx, hy] = cornerPoint(room, corner);
          group.append(
            el("rect", {
              class: "handle",
              "data-handle": corner,
              "data-room": room.id,
              x: hx - size / 2,
              y: hy - size / 2,
              width: size,
              height: size,
            }),
          );
        }
      }
      rooms.append(group);
    }
  }
  const radius = 13 * unit;
  for (const incident of state.visible) {
    const selected = incident.id === state.selectedId;
    const group = el("g", {
      class: "pin",
      "data-pin": incident.id,
      transform: `translate(${incident.x} ${incident.y})`,
    });
    const circle = el("circle", {
      class: `pin-shape ${incident.severity}${selected ? " selected" : ""}`,
      r: selected ? radius * 1.15 : radius,
    });
    const number = el("text", { class: "pin-number", "font-size": 12 * unit });
    number.textContent = String(incident.number);
    group.append(circle, number);
    pins.append(group);
  }
}

function cornerPoint(room, corner) {
  const x = corner.includes("w") ? room.x : room.x + room.w;
  const y = corner.includes("n") ? room.y : room.y + room.h;
  return [x, y];
}

function updateCounts() {
  for (const room of state.rooms) {
    const node = roomsPanel.querySelector(`[data-count="${room.id}"]`);
    if (!node) continue;
    const count = state.visible.filter((item) => item.room_id === room.id).length;
    node.textContent = count ? String(count) : "";
  }
}

function fieldsFor(kind) {
  if (kind === "kitchen") return ["ventilation", "cooktop", "open_plan"];
  if (kind === "bedroom") return ["egress", "smoke_alarm"];
  if (kind === "bath") return ["ventilation", "tub"];
  if (kind === "laundry") return ["dryer", "dryer_vented", "egress"];
  if (kind === "hall") return ["smoke_alarm"];
  if (kind === "living") return [];
  return ["ventilation", "egress", "cooktop", "dryer", "tub", "smoke_alarm"];
}

function renderRoomList() {
  const selected = state.rooms.find((room) => room.id === state.selectedRoomId);
  roomsPanel.replaceChildren(
    h("h2", {}, "Rooms"),
    h("p", { class: "panel-note" }, "Change what a room has. The marks follow."),
  );
  if (!state.rooms.length) {
    roomsPanel.append(h("p", { class: "empty" }, "No rooms yet. Add one, or upload a plan with room names on it."));
    return;
  }
  for (const room of state.rooms) {
    const count = state.visible.filter((item) => item.room_id === room.id).length;
    const row = h(
      "button",
      {
        type: "button",
        class: room.id === state.selectedRoomId ? "room-row selected" : "room-row",
        onclick: () => {
          state.selectedRoomId = room.id;
          const incident = state.visible.find((item) => item.room_id === room.id);
          if (incident) state.selectedId = incident.id;
          renderRoomList();
          renderAnnotations();
          renderFindings();
        },
      },
      [
        h("span", { class: "room-name" }, room.name),
        h("span", { class: "count", "data-count": room.id }, count ? String(count) : ""),
        h("span", { class: "room-kind" }, KIND_LABELS[room.kind] || room.kind),
      ],
    );
    roomsPanel.append(row);
    if (room !== selected) continue;
    roomsPanel.append(roomForm(room));
  }
}

function roomForm(room) {
  const form = h("div", { class: "room-form" });
  const name = h("input", { type: "text", value: room.name, "aria-label": "Room name" });
  name.addEventListener("input", () => {
    room.name = name.value;
    const label = svg.querySelector(`[data-room="${room.id}"] .room-label`);
    if (label) label.textContent = room.name;
    const title = roomsPanel.querySelector(".room-row.selected .room-name");
    if (title) title.textContent = room.name;
    renderFindings();
  });
  form.append(h("label", {}, ["Name", name]));

  const kind = h("select", { "aria-label": "Room type" }, [
    ...Object.entries(KIND_LABELS).map(([value, label]) => h("option", { value, selected: value === room.kind }, label)),
  ]);
  kind.value = room.kind;
  kind.addEventListener("change", () => {
    room.kind = kind.value;
    if (room.kind === "kitchen") {
      room.cooktop = true;
      room.open_plan = /open/i.test(room.name);
    }
    if (room.kind === "laundry") room.dryer = !/room/i.test(room.name);
    renderRoomList();
    analyze();
  });
  form.append(h("label", {}, ["Type", kind]));

  for (const field of fieldsFor(room.kind)) {
    if (field === "dryer_vented" && !room.dryer) continue;
    form.append(fieldControl(room, field));
  }
  if (!fieldsFor(room.kind).length) {
    form.append(h("p", { class: "panel-note" }, "No incident is tied to this room. Add a mark if you want to note one."));
  }
  form.append(
    h("button", {
      type: "button",
      class: "text-button",
      onclick: () => {
        state.rooms = state.rooms.filter((item) => item.id !== room.id);
        state.selectedRoomId = state.rooms[0]?.id || null;
        renderRoomList();
        analyze();
      },
    }, "Remove room"),
  );
  return form;
}

function fieldControl(room, field) {
  if (field === "ventilation") {
    const select = h("select", {}, [
      h("option", { value: "none" }, "Not drawn"),
      h("option", { value: "window" }, "Window"),
      h("option", { value: "exhaust_fan" }, "Exhaust fan"),
      h("option", { value: "range_hood" }, "Range hood"),
    ]);
    select.value = room.ventilation || "none";
    select.addEventListener("change", () => {
      room.ventilation = select.value;
      analyze();
    });
    return h("label", {}, ["Ventilation", select]);
  }
  if (field === "egress") {
    const select = h("select", {}, [
      h("option", { value: "none" }, "Not drawn"),
      h("option", { value: "window" }, "Egress window"),
      h("option", { value: "exterior_door" }, "Exterior door"),
    ]);
    select.value = room.egress || "none";
    select.addEventListener("change", () => {
      room.egress = select.value;
      analyze();
    });
    return h("label", {}, ["Way out", select]);
  }
  const labels = {
    cooktop: "Cooktop",
    open_plan: "Open to the living space",
    dryer: "Dryer",
    dryer_vented: "Dryer vented outside",
    tub: "Bathtub",
    smoke_alarm: "Smoke alarm in this room",
  };
  const input = h("input", { type: "checkbox", checked: Boolean(room[field]) });
  input.addEventListener("change", () => {
    room[field] = input.checked;
    if (field === "dryer") renderRoomList();
    analyze();
  });
  return h("label", { class: "check-row" }, [input, labels[field]]);
}

function renderFindings() {
  const items = state.visible.length || state.ruleIncidents.length || state.custom.length ? visibleIncidents() : [];
  const highs = items.filter((item) => item.severity === "high").length;
  const mediums = items.filter((item) => item.severity === "medium").length;
  findingsPanel.replaceChildren(h("h2", {}, "Likely incidents"));
  const summary = items.length
    ? `${items.length} mark${items.length === 1 ? "" : "s"} · ${highs} high · ${mediums} medium`
    : "Nothing is flagged with the current room settings.";
  findingsPanel.append(h("p", { class: "summary" }, summary));

  const selected = items.find((item) => item.id === state.selectedId) || items[0];
  if (selected) findingsPanel.append(detailBlock(selected));

  if (!items.length) {
    findingsPanel.append(
      h("p", { class: "empty" }, "Mark a cooktop with no ventilation, a bedroom with no way out, or a dryer with no duct, and a suggestion appears here."),
    );
  }
  for (const incident of items) {
    findingsPanel.append(incidentRow(incident));
  }

  const hidden = state.ruleIncidents.filter((item) => state.dismissed[item.id]);
  if (!hidden.length) return;
  const block = h("div", { class: "hidden-block" });
  const list = h("div");
  for (const incident of hidden) {
    list.append(
      h("button", {
        type: "button",
        class: "text-button",
        onclick: () => {
          delete state.dismissed[incident.id];
          state.selectedId = incident.id;
          visibleIncidents();
          renderFindings();
          renderAnnotations();
          updateCounts();
        },
      }, `Restore “${incident.title}”`),
    );
  }
  block.append(h("details", {}, [h("summary", {}, `${hidden.length} hidden`), list]));
  findingsPanel.append(block);
}

function incidentRow(incident) {
  return h(
    "button",
    {
      type: "button",
      class: incident.id === state.selectedId ? "incident selected" : "incident",
      onclick: () => selectIncident(incident.id),
    },
    [
      h("span", { class: "incident-title" }, `${incident.number}. ${incident.title}`),
      h("span", { class: `severity ${incident.severity}` }, incident.severity),
      h("span", { class: "incident-place" }, placeName(incident)),
    ],
  );
}

function detailBlock(incident) {
  const detail = h("div", { class: "detail" });
  detail.append(
    h("span", { class: `severity ${incident.severity}` }, incident.severity),
    h("h3", {}, incident.title),
    h("p", { class: "incident-place" }, placeName(incident)),
  );
  if (incident.custom) {
    detail.append(customEditor(incident));
    return detail;
  }
  detail.append(h("p", { class: "why" }, incident.why));
  detail.append(
    h("div", { class: `fix ${incident.severity}` }, [
      h("p", { class: "fix-label" }, "Suggested fix"),
      h("p", {}, incident.suggestion),
    ]),
  );
  detail.append(
    h("div", { class: "detail-actions" }, [
      h("button", {
        type: "button",
        class: "text-button",
        onclick: () => {
          state.dismissed[incident.id] = true;
          state.selectedId = null;
          visibleIncidents();
          renderFindings();
          renderAnnotations();
          updateCounts();
        },
      }, "Not an issue"),
    ]),
  );
  return detail;
}

function customEditor(incident) {
  const wrap = h("div", { class: "room-form" });
  const severity = h("select", {}, [
    h("option", { value: "high" }, "High"),
    h("option", { value: "medium" }, "Medium"),
    h("option", { value: "low" }, "Low"),
  ]);
  severity.value = incident.severity;
  severity.addEventListener("change", () => {
    const stored = state.custom.find((item) => item.id === incident.id);
    if (stored) stored.severity = severity.value;
    visibleIncidents();
    renderAnnotations();
    renderFindings();
  });
  const title = h("input", { type: "text", value: incident.title });
  title.addEventListener("input", () => {
    const stored = state.custom.find((item) => item.id === incident.id);
    if (stored) stored.title = title.value;
  });
  const why = h("textarea", {}, incident.why || "");
  why.addEventListener("input", () => {
    const stored = state.custom.find((item) => item.id === incident.id);
    if (stored) stored.why = why.value;
  });
  const suggestion = h("textarea", {}, incident.suggestion || "");
  suggestion.addEventListener("input", () => {
    const stored = state.custom.find((item) => item.id === incident.id);
    if (stored) stored.suggestion = suggestion.value;
  });
  wrap.append(
    h("label", {}, ["Severity", severity]),
    h("label", {}, ["Title", title]),
    h("label", {}, ["Why it is likely", why]),
    h("label", {}, ["Suggested fix", suggestion]),
    h("button", {
      type: "button",
      class: "text-button",
      onclick: () => {
        state.custom = state.custom.filter((item) => item.id !== incident.id);
        state.selectedId = null;
        visibleIncidents();
        renderFindings();
        renderAnnotations();
      },
    }, "Remove mark"),
  );
  return wrap;
}

function applyPlan(payload) {
  state.width = payload.width;
  state.height = payload.height;
  state.paths = payload.paths || [];
  state.rooms = payload.rooms || [];
  state.imageUrl = payload.image_url || "";
  state.name = payload.name || "Plan";
  state.notice = payload.notice || "";
  state.custom = payload.custom || [];
  state.dismissed = {};
  for (const id of payload.dismissed || []) state.dismissed[id] = true;
  state.pinOverrides = payload.pinOverrides || {};
  state.ruleIncidents = [];
  state.selectedId = null;
  state.selectedRoomId = state.rooms[0]?.id || null;
  state.showPhoto = false;
  document.getElementById("show-photo").checked = false;
  cam.x = 0;
  cam.y = 0;
  cam.w = state.width;
  cam.h = state.height;
  applyCam();
  renderPaths();
  renderRoomList();
  setHint("Reading the plan…");
  requestAnimationFrame(() => analyze());
}

async function loadSample() {
  setHint("Reading the sample plan…");
  const response = await fetch("/api/sample");
  if (!response.ok) {
    setHint("The sample plan could not be opened.", true);
    return;
  }
  applyPlan(await response.json());
}

async function readDrawing() {
  const button = document.getElementById("read-drawing");
  if (!state.imageUrl) {
    setHint("Open a plan before reading the drawing.", true);
    return;
  }
  button.disabled = true;
  setHint("Reading rooms and fixtures from the drawing…");
  try {
    const response = await fetch("/api/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_url: state.imageUrl }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload && payload.detail;
      throw new Error(typeof detail === "string" ? detail : "The drawing could not be read.");
    }
    state.rooms = payload.rooms || [];
    state.notice = payload.notice || "";
    state.pinOverrides = {};
    state.dismissed = {};
    state.selectedId = null;
    state.selectedRoomId = state.rooms[0]?.id || null;
    state.ruleIncidents = [];
    visibleIncidents();
    renderAnnotations();
    renderRoomList();
    analyze();
  } catch (error) {
    setHint(error.message || "The drawing could not be read.", true);
  } finally {
    button.disabled = false;
  }
}

async function upload(file) {
  setHint(`Converting ${file.name}…`);
  const body = new FormData();
  body.append("file", file);
  let payload;
  try {
    const response = await fetch("/api/plan", { method: "POST", body });
    payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Could not read that plan.");
  } catch (error) {
    setHint(error.message || "Could not read that plan.", true);
    return;
  }
  applyPlan(payload);
}

function setMode(mode) {
  state.mode = mode;
  svg.classList.toggle("add-room", mode === "add-room");
  svg.classList.toggle("add-mark", mode === "add-mark");
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
  showHint();
}

function onPointerDown(event) {
  if (event.button != null && event.button !== 0) return;
  const plan = clientToPlan(event.clientX, event.clientY);
  if (state.mode === "add-mark") {
    const room = roomAt(plan);
    const incident = {
      id: `custom-${customSerial++}`,
      room_id: room ? room.id : "plan",
      severity: "medium",
      priority: 50,
      title: "Incident",
      why: "",
      suggestion: "",
      place: room ? room.name : "Plan",
      x: plan.x,
      y: plan.y,
      custom: true,
    };
    state.custom.push(incident);
    state.selectedId = incident.id;
    if (room) state.selectedRoomId = room.id;
    setMode("select");
    visibleIncidents();
    renderAnnotations();
    renderFindings();
    renderRoomList();
    return;
  }
  const handle = event.target.closest?.("[data-handle]");
  const pin = event.target.closest?.("[data-pin]");
  const roomNode = event.target.closest?.("[data-room]");
  if (state.mode === "add-room") {
    drag = { type: "new-room", x: plan.x, y: plan.y };
    svg.setPointerCapture(event.pointerId);
    return;
  }
  if (handle) {
    const room = state.rooms.find((item) => item.id === handle.dataset.room);
    state.selectedRoomId = room.id;
    drag = { type: "resize", room, corner: handle.dataset.handle, origin: { ...room } };
  } else if (pin) {
    const incident = state.visible.find((item) => item.id === pin.dataset.pin);
    state.selectedId = incident.id;
    if (incident.room_id !== "plan") state.selectedRoomId = incident.room_id;
    drag = { type: "pin", incident };
    renderFindings();
    renderRoomList();
  } else if (roomNode) {
    const room = state.rooms.find((item) => item.id === roomNode.dataset.room);
    state.selectedRoomId = room.id;
    const incident = state.visible.find((item) => item.room_id === room.id);
    if (incident) state.selectedId = incident.id;
    drag = { type: "move", room, dx: plan.x - room.x, dy: plan.y - room.y };
    renderFindings();
    renderRoomList();
  } else {
    const matrix = svg.getScreenCTM();
    drag = {
      type: "pan",
      x: event.clientX,
      y: event.clientY,
      cam: { ...cam },
      scaleX: matrix ? matrix.a : 1,
      scaleY: matrix ? matrix.d : 1,
    };
    svg.classList.add("panning");
  }
  svg.setPointerCapture(event.pointerId);
  renderAnnotations();
}

function onPointerMove(event) {
  if (!drag) return;
  const plan = clientToPlan(event.clientX, event.clientY);
  if (drag.type === "pan") {
    cam.x = drag.cam.x - (event.clientX - drag.x) / drag.scaleX;
    cam.y = drag.cam.y - (event.clientY - drag.y) / drag.scaleY;
    applyCam();
    return;
  }
  if (drag.type === "move") {
    drag.room.x = plan.x - drag.dx;
    drag.room.y = plan.y - drag.dy;
    renderAnnotations();
    return;
  }
  if (drag.type === "resize") {
    resizeRoom(drag.room, drag.corner, drag.origin, plan);
    renderAnnotations();
    return;
  }
  if (drag.type === "pin") {
    drag.incident.x = plan.x;
    drag.incident.y = plan.y;
    if (drag.incident.custom) {
      const stored = state.custom.find((item) => item.id === drag.incident.id);
      if (stored) {
        stored.x = plan.x;
        stored.y = plan.y;
      }
    } else {
      state.pinOverrides[drag.incident.id] = { x: plan.x, y: plan.y };
    }
    renderAnnotations();
    return;
  }
  if (drag.type === "new-room") {
    drawPreview(drag.x, drag.y, plan.x, plan.y);
  }
}

function resizeRoom(room, corner, origin, plan) {
  let { x, y, w, h } = origin;
  if (corner.includes("e")) w = Math.max(36, plan.x - origin.x);
  if (corner.includes("s")) h = Math.max(36, plan.y - origin.y);
  if (corner.includes("w")) {
    const right = origin.x + origin.w;
    x = Math.min(plan.x, right - 36);
    w = right - x;
  }
  if (corner.includes("n")) {
    const bottom = origin.y + origin.h;
    y = Math.min(plan.y, bottom - 36);
    h = bottom - y;
  }
  room.x = x;
  room.y = y;
  room.w = w;
  room.h = h;
}

function drawPreview(x0, y0, x1, y1) {
  const rooms = svg.querySelector("#rooms");
  let preview = svg.querySelector("#preview");
  if (!preview) {
    preview = el("rect", { id: "preview", class: "room-shape selected" });
    rooms.append(preview);
  }
  preview.setAttribute("x", Math.min(x0, x1));
  preview.setAttribute("y", Math.min(y0, y1));
  preview.setAttribute("width", Math.abs(x1 - x0));
  preview.setAttribute("height", Math.abs(y1 - y0));
}

function onPointerUp() {
  if (!drag) return;
  const ended = drag;
  drag = null;
  svg.classList.remove("panning");
  svg.querySelector("#preview")?.remove();
  if (ended.type === "move" || ended.type === "resize") analyze();
}

svg.addEventListener("pointerdown", onPointerDown);
svg.addEventListener("pointermove", onPointerMove);
svg.addEventListener("pointerup", (event) => {
  lastPoint = { x: event.clientX, y: event.clientY };
  if (drag && drag.type === "new-room") {
    const start = drag;
    drag = null;
    svg.classList.remove("panning");
    svg.querySelector("#preview")?.remove();
    const plan = clientToPlan(event.clientX, event.clientY);
    const x = Math.min(start.x, plan.x);
    const y = Math.min(start.y, plan.y);
    const w = Math.abs(plan.x - start.x);
    const h = Math.abs(plan.y - start.y);
    if (w >= 24 && h >= 24) {
      const room = blankRoom({
        id: `room-${customSerial++}`,
        name: "Room",
        kind: "other",
        x,
        y,
        w,
        h,
      });
      state.rooms.push(room);
      state.selectedRoomId = room.id;
      setMode("select");
      renderRoomList();
      analyze();
    }
    return;
  }
  onPointerUp();
});

svg.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const plan = clientToPlan(event.clientX, event.clientY);
    const factor = event.deltaY > 0 ? 1.09 : 1 / 1.09;
    const nx = (plan.x - cam.x) / cam.w;
    const ny = (plan.y - cam.y) / cam.h;
    const aspect = state.height / state.width;
    cam.w = Math.min(state.width * 4, Math.max(state.width / 8, cam.w * factor));
    cam.h = cam.w * aspect;
    cam.x = plan.x - nx * cam.w;
    cam.y = plan.y - ny * cam.h;
    applyCam();
    renderAnnotations();
  },
  { passive: false },
);

document.getElementById("file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) upload(file);
  event.target.value = "";
});
document.getElementById("sample").addEventListener("click", loadSample);
document.getElementById("read-drawing").addEventListener("click", readDrawing);
document.getElementById("export").addEventListener("click", exportSvg);
document.getElementById("fit").addEventListener("click", () => {
  cam.x = 0;
  cam.y = 0;
  cam.w = state.width;
  cam.h = state.height;
  applyCam();
  renderAnnotations();
});
for (const button of document.querySelectorAll("[data-mode]")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}
document.getElementById("show-drawing").addEventListener("change", (event) => {
  state.showDrawing = event.target.checked;
  renderPaths();
});
document.getElementById("show-photo").addEventListener("change", (event) => {
  state.showPhoto = event.target.checked;
  renderPaths();
});
document.getElementById("show-rooms").addEventListener("change", (event) => {
  state.showRooms = event.target.checked;
  renderAnnotations();
});

let dragDepth = 0;
window.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dragDepth += 1;
  document.getElementById("drop").hidden = false;
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("dragleave", () => {
  dragDepth -= 1;
  if (dragDepth <= 0) {
    dragDepth = 0;
    document.getElementById("drop").hidden = true;
  }
});
window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  document.getElementById("drop").hidden = true;
  const file = event.dataTransfer.files[0];
  if (file) upload(file);
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setMode("select");
});

function xml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function wrap(text, width) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > width && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

function exportSvg() {
  const items = visibleIncidents();
  const panelX = state.width + 40;
  const blocks = [];
  let cursor = 86;
  for (const item of items) {
    const why = wrap(item.why, 48);
    const suggestion = wrap(item.suggestion, 48);
    const height = 26 + why.length * 18 + 24 + suggestion.length * 18 + 16;
    blocks.push({ item, why, suggestion, y: cursor });
    cursor += height;
  }
  const totalW = state.width + 520;
  const totalH = Math.max(state.height, cursor + 28);
  const colors = { high: "#8d2e22", medium: "#8a5a12", low: "#2c5b42" };
  const paths = state.showDrawing
    ? state.paths
        .map((path) => `<path d="${path.d}" fill="#1c1915" fill-rule="evenodd"/>`)
        .join("")
    : "";
  const rooms = state.rooms
    .map(
      (room) =>
        `<rect x="${room.x}" y="${room.y}" width="${room.w}" height="${room.h}" fill="rgba(30,58,86,0.04)" stroke="#1e3a56" stroke-dasharray="5 4"/>` +
        `<text x="${room.x + 8}" y="${room.y + 18}" fill="#1e3a56" font-size="14">${xml(room.name)}</text>`,
    )
    .join("");
  const pins = items
    .map(
      (item) =>
        `<g transform="translate(${item.x} ${item.y})">` +
        `<circle r="14" fill="${colors[item.severity] || "#1c1915"}"/>` +
        `<text y="1" text-anchor="middle" dominant-baseline="central" fill="#fff" font-size="13" font-weight="650">${item.number}</text>` +
        `</g>`,
    )
    .join("");
  const notes = blocks
    .map(({ item, why, suggestion, y }) => {
      const whyText = why.map((line, index) => `<tspan x="${panelX}" dy="${index === 0 ? 0 : 18}">${xml(line)}</tspan>`).join("");
      const fixY = y + 22 + why.length * 18 + 8;
      const fixText = suggestion
        .map((line, index) => `<tspan x="${panelX}" dy="${index === 0 ? 0 : 18}">${xml(line)}</tspan>`)
        .join("");
      return (
        `<text x="${panelX}" y="${y}" fill="${colors[item.severity]}" font-size="12" font-weight="700">${item.number}. ${xml(item.severity.toUpperCase())} · ${xml(placeName(item))}</text>` +
        `<text x="${panelX}" y="${y + 20}" fill="#1c1915" font-size="16">${xml(item.title)}</text>` +
        `<text x="${panelX}" y="${y + 42}" fill="#1c1915" font-size="13">${whyText}</text>` +
        `<text x="${panelX}" y="${fixY}" fill="#6d665d" font-size="11">SUGGESTED FIX</text>` +
        `<text y="${fixY + 18}" fill="#1c1915" font-size="14">${fixText}</text>`
      );
    })
    .join("");
  const meta = JSON.stringify({
    width: state.width,
    height: state.height,
    paths: state.paths,
    rooms: state.rooms,
    custom: state.custom,
    dismissed: Object.keys(state.dismissed),
    pinOverrides: state.pinOverrides,
    name: state.name,
  }).replaceAll("]]>", "]] >");
  const svgText = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${totalW}" height="${totalH}" viewBox="0 0 ${totalW} ${totalH}" font-family="Avenir Next, Helvetica, sans-serif">
  <metadata id="floor-incident-state"><![CDATA[${meta}]]></metadata>
  <rect width="100%" height="100%" fill="#fbf8f3"/>
  <rect width="${state.width}" height="${state.height}" fill="#fbf8f3"/>
  <g id="drawing">${paths}</g>
  <g id="rooms">${rooms}</g>
  <g id="pins">${pins}</g>
  <text x="${panelX}" y="36" fill="#1c1915" font-size="22" font-family="Palatino, Georgia, serif">Likely incidents</text>
  <text x="${panelX}" y="58" fill="#6d665d" font-size="12">Based on what is drawn. Not a code inspection.</text>
  ${notes}
</svg>`;
  const blob = new Blob([svgText], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const base = (state.name || "floor-incidents").replace(/\.[^.]+$/, "");
  link.download = `${base}-incidents.svg`;
  link.click();
  URL.revokeObjectURL(url);
}

ensureSvg();
applyCam();
loadSample();
