"""
Hospital A* pathfinding over named zones (UCLA Medical Center, Santa Monica).

Each zone is a node: (floor_z, cx, cy) in a 1000×700 viewbox.
  floor_z : 0=Floor A (ground), 1–6 for floors 1–6
  cx, cy  : zone centroid in viewbox pixels

Scale / speed assumptions:
  1000 viewbox units ≈ 100 m  →  1 unit = 0.10 m
  Walking speed: 60 m/min
  Elevator: 1.5 min fixed wait + 0.5 min per floor level crossed

Public API
----------
  travel_minutes(from_zone, to_zone) -> float
      Estimated travel time in minutes.
  astar(start, goal) -> (path: list[str], cost: float)
      Full path (elevator nodes stripped) plus cost.
  zone_coords(zone) -> (floor_z, x, y) | None
      Raw coordinate lookup (None if zone unknown).
  room_to_zone(room_id) -> str
      Map a rooms.json room_id to its containing zone.
"""
from __future__ import annotations

import heapq
import math
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_M_PER_UNIT     = 0.10       # 1 viewbox unit = 0.10 m
_WALK_M_PER_MIN = 60.0       # walking speed
_COST_PER_UNIT  = _M_PER_UNIT / _WALK_M_PER_MIN   # min per viewbox unit
_ELEV_WAIT      = 1.5        # fixed elevator wait (min)
_ELEV_PER_FLOOR = 0.5        # added per floor level (min)

# ---------------------------------------------------------------------------
# Zone registry  zone_id -> (floor_z, cx, cy)
# Wing centroids (from floorData.ts WING_RECTS):
#   southwest: (220, 350)  central: (530, 350)
#   north:     (770, 390)  orthopaedic: (810, 140)
# ---------------------------------------------------------------------------
ZONES: dict[str, tuple[int, float, float]] = {
    # ---- Floor A (z=0) ----
    "er":                (0, 220, 350),
    "admissions":        (0, 530, 350),
    "parking_garage":    (0, 220, 500),
    "sw_lobby":          (0, 220, 420),
    "admin":             (0, 770, 390),
    "mn_pavilion":       (0, 230, 615),

    # ---- Floor 1 (z=1) ----
    "perinatal_center":  (1, 220, 250),
    "perinatal_services":(1, 220, 350),
    "mpu":               (1, 530, 250),
    "outpatient_1401":   (1, 530, 350),

    # ---- Floor 2 (z=2) ----
    "labor_delivery":    (2, 220, 250),
    "nicu":              (2, 530, 250),
    "nursery":           (2, 530, 350),
    "postpartum":        (2, 530, 420),
    "radiology":         (2, 770, 390),
    "floor_2_corridor":  (2, 530, 350),

    # ---- Floor 3 (z=3) — surgical / rehab / ortho ----
    "or_1":              (3, 130, 250),
    "or_2":              (3, 220, 300),
    "or_3":              (3, 130, 450),
    "surg_intervention": (3, 220, 257),
    "surg_services":     (3, 530, 257),
    "floor_3_corridor":  (3, 530, 350),
    "nurses_station":    (3, 480, 300),
    "nurses_station_2":  (3, 580, 300),
    "break_room":        (3, 480, 420),
    "break_room_1":      (3, 480, 420),
    "break_room_2":      (3, 580, 420),
    "rehab":             (3, 770, 390),
    "rehabilitation":    (3, 770, 390),
    "ortho_unit":        (3, 810, 140),

    # ---- Floor 4 (z=4) — ICU / PICU / oncology ----
    "icu":               (4, 770, 390),
    "picu":              (4, 530, 450),
    "med_surg_central":  (4, 530, 257),
    "oncology_unit":     (4, 810, 140),
    "oncology":          (4, 810, 140),
    "floor_4_corridor":  (4, 530, 350),

    # ---- Floor 5 (z=5) — IMCU / geriatric ----
    "imcu":              (5, 530, 257),
    "geriatric_unit":    (5, 770, 390),
    "geriatric":         (5, 770, 390),
    "floor_5_corridor":  (5, 530, 350),

    # ---- Floor 6 (z=6) — pediatric / teen ----
    "teen_center":       (6, 770, 250),
    "pediatric_unit":    (6, 770, 390),
    "pediatric":         (6, 770, 390),
    "floor_6_corridor":  (6, 530, 350),
}

# One elevator hub per floor at (z, 530, 160) — top of the central wing.
for _z in range(7):
    ZONES[f"elev_{_z}"] = (_z, 530.0, 160.0)

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
_GRAPH: dict[str, list[tuple[str, float]]] = {z: [] for z in ZONES}


def _walk_cost(a: str, b: str) -> float:
    _, ax, ay = ZONES[a]
    _, bx, by = ZONES[b]
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2) * _COST_PER_UNIT


def _add(a: str, b: str, cost: Optional[float] = None) -> None:
    c = _walk_cost(a, b) if cost is None else cost
    _GRAPH[a].append((b, c))
    _GRAPH[b].append((a, c))


# 1. Star topology: every non-elevator zone connects to its floor elevator hub.
#    This guarantees full connectivity for any zone pair.
for _zid, (_fz, _cx, _cy) in list(ZONES.items()):
    if not _zid.startswith("elev_"):
        _add(_zid, f"elev_{_fz}")

# 2. Elevator shaft: adjacent floor hubs connect (central shaft only).
for _fz in range(6):
    _add(f"elev_{_fz}", f"elev_{_fz + 1}", _ELEV_WAIT + _ELEV_PER_FLOOR)

# 3. Corridor shortcuts: same-floor adjacencies that are faster than going
#    through the elevator hub.
_SHORTCUTS: list[tuple[str, str]] = [
    # Floor A
    ("er", "admissions"), ("er", "sw_lobby"), ("admissions", "admin"),
    # Floor 1
    ("perinatal_center", "perinatal_services"), ("mpu", "outpatient_1401"),
    ("perinatal_center", "mpu"),
    # Floor 2
    ("labor_delivery", "nicu"), ("nicu", "nursery"), ("nursery", "postpartum"),
    ("radiology", "nicu"), ("floor_2_corridor", "nicu"),
    ("floor_2_corridor", "labor_delivery"), ("floor_2_corridor", "radiology"),
    # Floor 3
    ("or_1", "surg_intervention"), ("or_2", "surg_intervention"),
    ("or_3", "surg_intervention"), ("surg_intervention", "floor_3_corridor"),
    ("surg_services", "floor_3_corridor"),
    ("nurses_station", "floor_3_corridor"),
    ("nurses_station_2", "floor_3_corridor"),
    ("break_room", "floor_3_corridor"), ("break_room_1", "floor_3_corridor"),
    ("break_room_2", "floor_3_corridor"),
    ("rehab", "floor_3_corridor"), ("rehabilitation", "rehab"),
    ("ortho_unit", "floor_3_corridor"),
    ("nurses_station", "nurses_station_2"),
    ("break_room", "break_room_1"), ("break_room_1", "break_room_2"),
    # Floor 4
    ("icu", "floor_4_corridor"), ("picu", "floor_4_corridor"),
    ("med_surg_central", "floor_4_corridor"),
    ("oncology_unit", "floor_4_corridor"), ("oncology", "oncology_unit"),
    # Floor 5
    ("imcu", "floor_5_corridor"), ("geriatric_unit", "floor_5_corridor"),
    ("geriatric", "geriatric_unit"),
    # Floor 6
    ("teen_center", "floor_6_corridor"), ("pediatric_unit", "floor_6_corridor"),
    ("pediatric", "pediatric_unit"), ("teen_center", "pediatric_unit"),
]

for _a, _b in _SHORTCUTS:
    if _a in ZONES and _b in ZONES:
        _add(_a, _b)

# ---------------------------------------------------------------------------
# Room → zone mapping  (rooms.json room_id → zone string)
# ---------------------------------------------------------------------------
ROOM_TO_ZONE: dict[str, str] = {
    # Floor 1 (ED)
    "room_101": "er", "room_102": "er", "room_103": "er", "room_104": "er",
    "ed_station": "er", "trauma_bay": "er",
    # Floor 2 (ICU / OR / ward)
    "room_icu_a": "icu", "room_icu_b": "icu", "room_icu_c": "icu",
    "icu_station": "icu",
    "or_1": "or_1", "or_2": "or_2", "or_prep": "or_2",
    "room_201": "floor_2_corridor", "room_208": "floor_2_corridor",
    "room_214": "floor_2_corridor",
    "nurses_station_2": "nurses_station_2",
    "break_room_2": "break_room_2",
    "floor_2_corridor": "floor_2_corridor",
    # Floor 3 (ward)
    "room_301": "floor_3_corridor", "room_302": "floor_3_corridor",
    "room_305": "floor_3_corridor", "room_310": "floor_3_corridor",
    "nurses_station_3": "nurses_station",
    "break_room_1": "break_room_1",
    "floor_3_corridor": "floor_3_corridor",
}


def room_to_zone(room_id: str) -> str:
    """Map a rooms.json room_id to its containing zone. Falls back to the
    room_id itself if it is already a known zone, otherwise 'floor_3_corridor'."""
    rid = room_id.strip().lower()
    if rid in ROOM_TO_ZONE:
        return ROOM_TO_ZONE[rid]
    if rid in ZONES:
        return rid
    # Numeric room pattern: extract floor digit
    digits = "".join(c for c in rid if c.isdigit())
    if digits:
        floor_digit = digits[0]
        floor_zone_map = {
            "1": "er",
            "2": "floor_2_corridor",
            "3": "floor_3_corridor",
            "4": "floor_4_corridor",
            "5": "floor_5_corridor",
            "6": "floor_6_corridor",
        }
        return floor_zone_map.get(floor_digit, "floor_3_corridor")
    return "floor_3_corridor"


# ---------------------------------------------------------------------------
# A* search
# ---------------------------------------------------------------------------
def _heuristic(a: str, b: str) -> float:
    az, ax, ay = ZONES[a]
    bz, bx, by = ZONES[b]
    horiz = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2) * _COST_PER_UNIT
    # Minimum vertical cost: no elevator wait, just per-floor time
    vert = abs(bz - az) * _ELEV_PER_FLOOR
    return horiz + vert


def astar(start: str, goal: str) -> tuple[list[str], float]:
    """Return (path, cost_minutes). Elevator hub nodes are stripped from path."""
    start = start.strip().lower()
    goal = goal.strip().lower()

    if start == goal:
        return [start], 0.0

    if start not in ZONES or goal not in ZONES:
        # One or both zones unknown — return a safe default estimate
        if start in ZONES and goal not in ZONES:
            return [start, goal], 3.0
        if start not in ZONES and goal in ZONES:
            return [start, goal], 3.0
        return [start, goal], 3.0

    # (f_cost, tie_breaker, node, path, g_cost)
    counter = 0
    open_heap: list[tuple[float, int, str, list[str], float]] = []
    heapq.heappush(open_heap, (_heuristic(start, goal), counter, start, [start], 0.0))
    best_g: dict[str, float] = {}

    while open_heap:
        f, _, cur, path, g = heapq.heappop(open_heap)

        if cur in best_g and best_g[cur] <= g:
            continue
        best_g[cur] = g

        if cur == goal:
            clean = [n for n in path if not n.startswith("elev_")]
            return clean or [start, goal], g

        for nbr, edge_cost in _GRAPH.get(cur, []):
            ng = g + edge_cost
            if nbr not in best_g or best_g[nbr] > ng:
                counter += 1
                heapq.heappush(
                    open_heap,
                    (ng + _heuristic(nbr, goal), counter, nbr, path + [nbr], ng),
                )

    # No path found — straight-line fallback
    az, ax, ay = ZONES[start]
    bz, bx, by = ZONES[goal]
    horiz = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2) * _COST_PER_UNIT
    vert = abs(bz - az) * (_ELEV_WAIT + _ELEV_PER_FLOOR) if az != bz else 0.0
    return [start, goal], horiz + vert


def travel_minutes(from_zone: str, to_zone: str) -> float:
    """Estimated travel time in minutes between two hospital zones."""
    _, cost = astar(from_zone, to_zone)
    return cost


def zone_coords(zone: str) -> Optional[tuple[int, float, float]]:
    """Return (floor_z, x, y) for a zone, or None if unknown."""
    return ZONES.get(zone.strip().lower())
