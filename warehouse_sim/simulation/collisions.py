"""Independently check saved positions, without reading the planner's reservations."""

from itertools import combinations

from ..algorithms.planner import manhattan


def audit_trajectory(scenario, rows, last_tick):
    starts = {vehicle.id: tuple(vehicle.start) for vehicle in scenario.vehicles}
    if type(last_tick) is not int or not 0 <= last_tick <= scenario.max_steps:
        raise ValueError("Invalid simulation_steps in summary")
    frames = [{} for _ in range(last_tick + 1)]
    for row in rows:
        tick, vehicle_id = int(row["time"]), row["vehicle_id"]
        if not 0 <= tick <= last_tick or vehicle_id not in starts or vehicle_id in frames[tick]:
            raise ValueError(f"Invalid or duplicate trace entry for {vehicle_id} at t={tick}")
        cell = (int(row["x"]), int(row["y"]))
        if not scenario.grid.walkable(cell):
            raise ValueError(f"{vehicle_id} is outside the walkable grid at t={tick}")
        frames[tick][vehicle_id] = cell
    if frames[0] != starts:
        raise ValueError("Initial frame differs from the scenario start positions")
    vertices = swaps = 0
    first = None
    pairs = list(combinations(starts, 2))
    for tick, frame in enumerate(frames):
        if frame.keys() != starts.keys():
            raise ValueError(f"Missing vehicle position at t={tick}")
        before = frames[tick - 1] if tick else frame
        for vehicle_id, cell in frame.items():
            if manhattan(before[vehicle_id], cell) > 1:
                raise ValueError(f"Illegal move by {vehicle_id} at t={tick}")
        for a, b in pairs:
            if frame[a] == frame[b]:
                vertices += 1
                first = first or {"type": "vertex", "time": tick, "vehicles": [a, b]}
            elif tick and before[a] == frame[b] and before[b] == frame[a]:
                swaps += 1
                first = first or {"type": "edge_swap", "time": tick, "vehicles": [a, b]}
    return {
        "checked_frames": len(frames), "vertex_conflicts": vertices, "edge_swap_conflicts": swaps,
        "conflict_count": vertices + swaps, "first_conflict": first,
    }
