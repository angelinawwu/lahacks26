// Source of truth for hospital floor layouts (UCLA Medical Center, Santa Monica).
// All coordinates are in a normalized 0–1000 x 0–700 viewBox.

export type FloorId = "A" | "1" | "2" | "3" | "4" | "5" | "6";
export type WingId =
  | "southwest"
  | "central"
  | "north"
  | "orthopaedic"
  | "merle_norman";

export type Rect = { x: number; y: number; w: number; h: number };

export type RoomDef = {
  id: string;
  name: string;
  wing: WingId;
  rect: Rect;
  isPatientRange?: boolean;
};

export type FloorDef = {
  id: FloorId;
  label: string;
  wings: WingId[];
  rooms: RoomDef[];
};

export const FLOOR_IDS: FloorId[] = ["A", "1", "2", "3", "4", "5", "6"];

export const WING_RECTS: Record<WingId, Rect> = {
  southwest: { x: 40, y: 160, w: 360, h: 380 },
  central: { x: 400, y: 160, w: 260, h: 380 },
  north: { x: 660, y: 240, w: 220, h: 300 },
  orthopaedic: { x: 660, y: 40, w: 300, h: 200 },
  merle_norman: { x: 80, y: 560, w: 300, h: 110 },
};

export const WING_COLORS: Record<WingId, { fill: string; stroke: string; label: string }> = {
  southwest: { fill: "#E5E9F2", stroke: "#94A3B8", label: "Southwest Wing" },
  central: { fill: "#EEEEEE", stroke: "#9CA3AF", label: "Central Wing" },
  north: { fill: "#E4EFE4", stroke: "#86A786", label: "North Wing" },
  orthopaedic: { fill: "#EDE7F4", stroke: "#A491B8", label: "Orthopaedic Wing" },
  merle_norman: { fill: "#F4ECDC", stroke: "#BFA77A", label: "Merle Norman Pavilion" },
};

export const STATUS_COLORS: Record<string, string> = {
  available: "#1D9E75",
  paging: "#378ADD",
  in_procedure: "#7F77DD",
  on_case: "#BA7517",
  off_shift: "#9CA3AF",
};

export const PRIORITY_PULSE: Record<string, { color: string; opacity: number }> = {
  P1: { color: "#E24B4A", opacity: 0.32 },
  P2: { color: "#E0A23A", opacity: 0.28 },
  P3: { color: "#3F8FE0", opacity: 0.18 },
  P4: { color: "#9CA3AF", opacity: 0.14 },
};

// Subdivide a wing into stacked horizontal rows for room rects.
function row(wing: WingId, idx: number, total: number, span = 1): Rect {
  const w = WING_RECTS[wing];
  const pad = 8;
  const rowH = (w.h - pad * 2) / total;
  return {
    x: w.x + pad,
    y: w.y + pad + idx * rowH,
    w: w.w - pad * 2,
    h: rowH * span - 4,
  };
}

type R = [WingId, number, number, string, string, boolean?]; // [wing, idx, total, id, name, isRange?]

function build(rs: R[]): RoomDef[] {
  return rs.map(([wing, idx, total, id, name, isRange]) => ({
    id,
    name,
    wing,
    rect: row(wing, idx, total),
    isPatientRange: !!isRange,
  }));
}

export const FLOORS: FloorDef[] = [
  {
    id: "A", label: "Floor A", wings: ["southwest", "central", "north", "orthopaedic", "merle_norman"],
    rooms: build([
      ["southwest", 0, 4, "er", "Emergency Room"],
      ["southwest", 1, 4, "cashier", "Cashier"],
      ["southwest", 2, 4, "chapel", "Chapel / Meditation"],
      ["southwest", 3, 4, "sw_lobby", "SW Lobby"],
      ["central", 0, 3, "admissions", "Admissions · Security · Conference Center"],
      ["central", 1, 3, "gift_cafe", "Gift Shop · Cafeteria"],
      ["central", 2, 3, "courtyard", "Courtyard / Outdoor Dining Terrace"],
      ["north", 0, 1, "admin", "Hospital & Nursing Administration"],
      ["orthopaedic", 0, 1, "ortho_entry", "Orthopaedic Wing Entrance"],
      ["merle_norman", 0, 1, "mn_pavilion", "Merle Norman Pavilion"],
    ]),
  },
  {
    id: "1", label: "Floor 1", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["southwest", 0, 2, "perinatal_center", "Perinatal Center"],
      ["southwest", 1, 2, "perinatal_services", "Perinatal Services"],
      ["central", 0, 3, "mpu", "Medical Procedures Unit"],
      ["central", 1, 3, "outpatient_1401", "Outpatient Services · Suite 1401"],
      ["central", 2, 3, "terrace", "Terrace (outdoor)"],
    ]),
  },
  {
    id: "2", label: "Floor 2", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["southwest", 0, 4, "labor_delivery", "Labor & Delivery"],
      ["southwest", 1, 4, "ld_waiting", "L&D / NICU Waiting"],
      ["southwest", 2, 4, "rooms_2412", "Patient Rooms 2412–2494", true],
      ["southwest", 3, 4, "rooms_2510", "Patient Rooms 2510–2536", true],
      ["central", 0, 3, "nicu", "NICU"],
      ["central", 1, 3, "nursery", "Nursery"],
      ["central", 2, 3, "postpartum", "Postpartum Unit"],
      ["north", 0, 1, "radiology", "Radiology · CT / MRI / X-Ray / US / Fluoro"],
      ["orthopaedic", 0, 2, "luskin_2100", "Luskin Children's Clinic · Suite 2100"],
      ["orthopaedic", 1, 2, "ortho_outpatient_2100", "Orthopaedic Outpatient · Suite 2100"],
    ]),
  },
  {
    id: "3", label: "Floor 3", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["southwest", 0, 2, "surg_intervention", "Surgical & Interventional Services"],
      ["southwest", 1, 2, "surg_waiting_3500", "Surgical Waiting · Suite 3500"],
      ["central", 0, 1, "surg_services", "Surgical Services"],
      ["north", 0, 1, "rehab", "Rehabilitation Services"],
      ["orthopaedic", 0, 2, "ortho_unit", "Orthopaedic Unit"],
      ["orthopaedic", 1, 2, "rooms_3204", "Patient Rooms 3204–3266", true],
    ]),
  },
  {
    id: "4", label: "Floor 4", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["southwest", 0, 1, "rooms_4410", "Patient Rooms 4410–4494", true],
      ["central", 0, 4, "med_surg_central", "Medicine / Surgery Unit"],
      ["central", 1, 4, "rooms_4318", "Patient Rooms 4318–4364", true],
      ["central", 2, 4, "picu", "PICU"],
      ["central", 3, 4, "pulm_mri", "Pulmonary Function Lab · MRI"],
      ["north", 0, 3, "med_surg_north", "Medicine / Surgery Unit"],
      ["north", 1, 3, "rooms_4204", "Patient Rooms 4204–4266", true],
      ["north", 2, 3, "icu", "ICU"],
      ["orthopaedic", 0, 2, "oncology", "Oncology Unit"],
      ["orthopaedic", 1, 2, "rooms_4502", "Patient Rooms 4502–4556", true],
    ]),
  },
  {
    id: "5", label: "Floor 5", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["southwest", 0, 1, "rooms_5410_sw", "Patient Rooms 5410–5498", true],
      ["central", 0, 2, "imcu", "Intermediate Care Unit"],
      ["central", 1, 2, "rooms_5410_c", "Patient Rooms 5410–5498", true],
      ["north", 0, 2, "geriatric", "Geriatric Unit"],
      ["north", 1, 2, "rooms_5204", "Patient Rooms 5204–5266", true],
    ]),
  },
  {
    id: "6", label: "Floor 6", wings: ["southwest", "central", "north", "orthopaedic"],
    rooms: build([
      ["north", 0, 3, "teen_center", "Teen Center"],
      ["north", 1, 3, "pediatric", "Pediatric Unit"],
      ["north", 2, 3, "rooms_6204", "Patient Rooms 6204–6266", true],
    ]),
  },
];

export function getFloor(id: FloorId): FloorDef {
  return FLOORS.find((f) => f.id === id) ?? FLOORS[0];
}

// Evenly distribute N points within a rect, returning {cx, cy} for each.
export function pinPositionsInRect(rect: Rect, count: number): { cx: number; cy: number }[] {
  if (count <= 0) return [];
  const cols = Math.ceil(Math.sqrt(count));
  const rows = Math.ceil(count / cols);
  const out: { cx: number; cy: number }[] = [];
  for (let i = 0; i < count; i++) {
    const r = Math.floor(i / cols);
    const c = i % cols;
    out.push({
      cx: rect.x + ((c + 0.5) * rect.w) / cols,
      cy: rect.y + ((r + 0.5) * rect.h) / rows,
    });
  }
  return out;
}

// Map a freeform zone string (from socket/TinyDB) onto a known floor + wing.
// Handles patterns like `floor_3_corridor`, `or_1`, `nurses_station`, `icu`, etc.
export function inferFloorWing(zone?: string | null): { floor: FloorId; wing: WingId } {
  // Normalize: lowercase + replace underscores with spaces so `\b` boundaries
  // work (in JS regex `_` is a word character, so `\bteen\b` won't match `teen_center`).
  const z = (zone ?? "").toLowerCase().trim().replace(/_/g, " ");

  // --- 1. Explicit keywords that pin to a specific floor+wing ---------------
  // Floor 6 — pediatric / teen
  if (/\b(teen|pediatric|peds|6204|6266)\b/.test(z)) return { floor: "6", wing: "north" };
  // Floor 5 — intermediate / geriatric
  if (/\b(imcu|intermediate)\b/.test(z)) return { floor: "5", wing: "central" };
  if (/\b(geriatric|5204|5266)\b/.test(z)) return { floor: "5", wing: "north" };
  if (/\b5410\b/.test(z)) return { floor: "5", wing: "southwest" };
  // Floor 4 — ICU / oncology / PICU / MRI
  if (/\b(picu|pulm|pulmonary|mri)\b/.test(z)) return { floor: "4", wing: "central" };
  if (/\b(icu|4204|4266)\b/.test(z)) return { floor: "4", wing: "north" };
  if (/\b(oncology|4502|4556)\b/.test(z)) return { floor: "4", wing: "orthopaedic" };
  if (/\b(4318|4364|4410|4494|med[_\s-]?surg)\b/.test(z)) return { floor: "4", wing: "central" };
  // Floor 3 — surgical / rehab / operating rooms
  if (/\b(or[_\s-]?\d+|operating[_\s-]?room|surgery|surgical|surg(?!ery)|post[_\s-]?op|pacu)\b/.test(z))
    return { floor: "3", wing: "southwest" };
  if (/\b(rehab|rehabilitation)\b/.test(z)) return { floor: "3", wing: "north" };
  if (/\b(ortho|orthopaedic|3204|3266)\b/.test(z)) return { floor: "3", wing: "orthopaedic" };
  // Floor 2 — L&D / NICU / radiology / imaging
  if (/\b(nicu|nursery|postpartum)\b/.test(z)) return { floor: "2", wing: "central" };
  if (/\b(radiology|imaging|ct[_\s-]?scan|x[_\s-]?ray|fluoro|ultrasound)\b/.test(z))
    return { floor: "2", wing: "north" };
  if (/\b(labor|delivery|l&d|2412|2510)\b/.test(z)) return { floor: "2", wing: "southwest" };
  if (/\b(luskin)\b/.test(z)) return { floor: "2", wing: "orthopaedic" };
  // Floor 1 — perinatal / outpatient
  if (/\b(perinatal|mpu|medical[_\s-]?procedures|outpatient|1401|terrace)\b/.test(z))
    return { floor: "1", wing: "central" };
  // Floor A — ER, admissions, cafeteria, parking, chapel
  if (/\b(er|emergency[_\s-]?room|trauma[_\s-]?bay|ambulance)\b/.test(z))
    return { floor: "A", wing: "southwest" };
  if (/\b(admissions|admitting|cashier|security|conference[_\s-]?center)\b/.test(z))
    return { floor: "A", wing: "central" };
  if (/\b(cafeteria|cafe|gift[_\s-]?shop|courtyard|dining)\b/.test(z))
    return { floor: "A", wing: "central" };
  if (/\b(chapel|meditation|sw[_\s-]?lobby|lobby)\b/.test(z))
    return { floor: "A", wing: "southwest" };
  if (/\b(parking|garage|loading[_\s-]?dock|basement)\b/.test(z))
    return { floor: "A", wing: "southwest" };
  if (/\b(admin|administration)\b/.test(z))
    return { floor: "A", wing: "north" };
  if (/\b(merle[_\s-]?norman|mn[_\s-]?pavilion|pavilion)\b/.test(z))
    return { floor: "A", wing: "merle_norman" };

  // --- 2. Fallback: extract explicit floor number from `floor_N_*` style ----
  const floorMatch = z.match(/floor[_\s-]?([a1-6])\b/);
  if (floorMatch) {
    const raw = floorMatch[1].toUpperCase();
    const floor: FloorId = (raw === "A" ? "A" : raw) as FloorId;
    // Try to infer wing from trailing descriptor.
    if (/north/.test(z)) return { floor, wing: "north" };
    if (/south|southwest|sw\b/.test(z)) return { floor, wing: "southwest" };
    if (/ortho/.test(z)) return { floor, wing: "orthopaedic" };
    if (/merle|pavilion/.test(z)) return { floor, wing: "merle_norman" };
    // Corridor / nurses station / break room — default to central hallway.
    return { floor, wing: "central" };
  }

  // --- 3. Floor-less generic zones (can't pin): keep as central/floor 3 ------
  if (/\b(nurses?[_\s-]?station|break[_\s-]?room|lounge|corridor|hallway)\b/.test(z))
    return { floor: "3", wing: "central" };

  return { floor: "3", wing: "central" };
}
