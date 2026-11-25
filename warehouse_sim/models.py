"""Validated input models. Coordinates are (x, y), origin at top left."""

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path

Cell = tuple[int, int]
AUTO_POLICIES = ("B0", "B1", "P")


def integer(value, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def cell(value, name: str) -> Cell:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be [x, y]")
    return integer(value[0], name), integer(value[1], name)


@dataclass(frozen=True)
class GridMap:
    name: str
    rows: tuple[str, ...]

    @property
    def width(self):
        return len(self.rows[0])

    @property
    def height(self):
        return len(self.rows)

    def walkable(self, pos: Cell) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height and self.rows[y][x] != "#"

    def neighbors(self, pos: Cell):
        x, y = pos
        # This order is part of the reproducibility contract.
        for candidate in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
            if self.walkable(candidate):
                yield candidate

    def cells(self, symbol: str):
        return [(x, y) for y, row in enumerate(self.rows) for x, c in enumerate(row) if c == symbol]

    def validate(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Map needs a non-empty name")
        if not self.rows or any(not isinstance(row, str) or not row for row in self.rows):
            raise ValueError("Map grid must contain non-empty strings")
        if any(len(row) != self.width for row in self.rows):
            raise ValueError("Map grid must be rectangular")
        if set("".join(self.rows)) - set("#.PUD"):
            raise ValueError("Map allows only # (obstacle), . (aisle), P, U, D")
        free = {(x, y) for y in range(self.height) for x in range(self.width) if self.walkable((x, y))}
        if not free:
            raise ValueError("Map has no walkable cells")
        start = min(free)
        seen, queue = {start}, deque([start])
        while queue:
            for pos in self.neighbors(queue.popleft()):
                if pos not in seen:
                    seen.add(pos)
                    queue.append(pos)
        if seen != free:
            raise ValueError("All walkable cells must be connected")

    def as_dict(self):
        return {"schema_version": 1, "name": self.name, "grid": list(self.rows)}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported map schema_version")
        result = cls(data["name"], tuple(data["grid"]))
        result.validate()
        return result


@dataclass(frozen=True)
class VehicleSpec:
    id: str
    start: Cell


@dataclass(frozen=True)
class TaskSpec:
    id: str
    release_time: int
    pickup: Cell
    delivery: Cell
    vehicle_id: str | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    grid: GridMap
    vehicles: tuple[VehicleSpec, ...]
    tasks: tuple[TaskSpec, ...]
    seed: int = 0
    pickup_steps: int = 1
    dropoff_steps: int = 1
    max_steps: int = 1000
    dispatch_policy: str = "fixed"
    dispatch_order: tuple[tuple[str, str], ...] = ()

    def validate(self):
        self.grid.validate()
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Scenario needs a non-empty name")
        integer(self.seed, "seed")
        integer(self.pickup_steps, "pickup_steps", 1)
        integer(self.dropoff_steps, "dropoff_steps", 1)
        integer(self.max_steps, "max_steps", 1)
        if self.dispatch_policy not in ("fixed", "ordered", *AUTO_POLICIES):
            raise ValueError("Unknown dispatch policy")
        if self.dispatch_policy != "fixed":
            if len(self.vehicles) not in (2, 4) or not self.tasks:
                raise ValueError("Automatic dispatch requires two or four vehicles and at least one task")
            if any(task.vehicle_id is not None for task in self.tasks):
                raise ValueError("Automatic dispatch tasks must omit vehicle_id")
        elif (len(self.vehicles), len(self.tasks)) not in ((1, 1), (2, 2)):
            raise ValueError("Use one vehicle and one task, or two vehicles with one fixed task each")
        for entity in (*self.vehicles, *self.tasks):
            if not isinstance(entity.id, str) or not entity.id:
                raise ValueError("Vehicle/task IDs must be non-empty strings")
        vehicle_ids = {vehicle.id for vehicle in self.vehicles}
        if self.dispatch_policy == "ordered":
            if (len(self.dispatch_order) != len(self.tasks)
                    or {task for task, _ in self.dispatch_order} != {task.id for task in self.tasks}
                    or any(vehicle not in vehicle_ids for _, vehicle in self.dispatch_order)):
                raise ValueError("An ordered reference must identify every task once and use known vehicles")
        elif self.dispatch_order:
            raise ValueError("Only an ordered reference can specify dispatch_order")
        if len(vehicle_ids) != len(self.vehicles) or len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Vehicle IDs and task IDs must be unique within their respective lists")
        for vehicle in self.vehicles:
            self._validate_position(vehicle.start, "P")
        if len({tuple(vehicle.start) for vehicle in self.vehicles}) != len(self.vehicles):
            raise ValueError("Vehicles must start in different cells")
        for task in self.tasks:
            integer(task.release_time, "release_time")
            if tuple(task.pickup) == tuple(task.delivery):
                raise ValueError("Pickup and delivery must be different cells")
            self._validate_position(task.pickup, "U")
            self._validate_position(task.delivery, "D")
            if task.vehicle_id is not None and (not isinstance(task.vehicle_id, str) or task.vehicle_id not in vehicle_ids):
                raise ValueError(f"Task {task.id} refers to an unknown vehicle")
        if self.dispatch_policy == "fixed" and len(self.vehicles) == 2 and {task.vehicle_id for task in self.tasks} != vehicle_ids:
            raise ValueError("Two-vehicle instances require exactly one fixed task per vehicle (task.vehicle_id)")

    def _validate_position(self, pos, symbol):
        pos = cell(pos, "coordinate")
        if not self.grid.walkable(pos):
            raise ValueError(f"Coordinate {pos} is blocked or outside map")
        if self.grid.rows[pos[1]][pos[0]] != symbol:
            raise ValueError(f"Coordinate {pos} must be marked {symbol} in map")

    def as_dict(self):
        return {
            "schema_version": 1, "name": self.name, "seed": self.seed,
            **({"dispatch_policy": self.dispatch_policy} if self.dispatch_policy != "fixed" else {}),
            **({"dispatch_order": [list(pair) for pair in self.dispatch_order]} if self.dispatch_order else {}),
            "map": self.grid.as_dict(),
            "parameters": {"pickup_steps": self.pickup_steps, "dropoff_steps": self.dropoff_steps, "max_steps": self.max_steps},
            "vehicles": [{"id": v.id, "start": list(v.start)} for v in self.vehicles],
            "tasks": [
                {"id": t.id, "release_time": t.release_time, "pickup": list(t.pickup), "delivery": list(t.delivery),
                 **({"vehicle_id": t.vehicle_id} if t.vehicle_id is not None else {})}
                for t in self.tasks
            ],
        }

    @classmethod
    def from_dict(cls, data, base_dir=Path(".")):
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported instance schema_version")
        map_data = data["map"]
        if isinstance(map_data, str):
            map_data = read_json(Path(base_dir) / map_data)
        params = data.get("parameters", {})
        result = cls(
            name=data["name"], grid=GridMap.from_dict(map_data),
            dispatch_policy=data.get("dispatch_policy", "fixed"),
            dispatch_order=tuple(tuple(pair) for pair in data.get("dispatch_order", ())),
            vehicles=tuple(VehicleSpec(v["id"], cell(v["start"], "start")) for v in data["vehicles"]),
            tasks=tuple(TaskSpec(t["id"], integer(t["release_time"], "release_time"), cell(t["pickup"], "pickup"), cell(t["delivery"], "delivery"), t.get("vehicle_id")) for t in data["tasks"]),
            seed=data.get("seed", 0), pickup_steps=params.get("pickup_steps", 1),
            dropoff_steps=params.get("dropoff_steps", 1), max_steps=params.get("max_steps", 1000),
        )
        result.validate()
        return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_scenario(path) -> Scenario:
    path = Path(path).resolve()
    return Scenario.from_dict(read_json(path), path.parent)
