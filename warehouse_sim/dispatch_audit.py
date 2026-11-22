"""Replay B0 decisions from task releases and positions in the saved trace."""

from collections import deque
import json

from .planner import distances_to


def audit_dispatch(scenario, trace, decisions, task_rows, last_tick):
    """Reconstruct eligible cars from prior awards and observed dropoffs."""
    frames = [{} for _ in range(last_tick + 1)]
    for row in trace:
        frames[int(row["time"])][row["vehicle_id"]] = row

    tasks = {task.id: task for task in scenario.tasks}
    ledger = {row["task_id"]: row for row in task_rows}
    if ledger.keys() != tasks.keys() or len(task_rows) != len(tasks):
        raise ValueError("Task ledger must contain one row per input task")
    queue = deque(sorted(tasks.values(), key=lambda task: (task.release_time, task.id)))
    distance_maps = {cell: distances_to(scenario.grid, cell) for cell in {task.pickup for task in tasks.values()}}
    busy, assigned, completed = {}, {}, {}
    for tick, frame in enumerate(frames):
        # A frame records the action just finished. Dispatch at t happens after this.
        for vehicle_id, row in frame.items():
            if vehicle_id not in busy and (row["phase"] != "idle" or row["action"] not in ("initial", "wait")):
                raise ValueError(f"t={tick}: {vehicle_id} acted without a dispatch")
        for vehicle_id, task_id in list(busy.items()):
            row = frame[vehicle_id]
            if row["task_id"] != task_id:
                raise ValueError(f"t={tick}: trajectory for {vehicle_id} must show {task_id}")
            if row["action"] == "dropoff" and row["task_status"] == "completed":
                if (int(row["x"]), int(row["y"])) != tasks[task_id].delivery:
                    raise ValueError(f"t={tick}: {task_id} completed at the wrong cell")
                completed[task_id] = tick
                del busy[vehicle_id]
        if tick == last_tick:
            break
        idle = frame.keys() - busy.keys()
        while idle and queue and queue[0].release_time <= tick:
            task = queue.popleft()
            distances = {
                vehicle: distance_maps[task.pickup][int(frame[vehicle]["x"]), int(frame[vehicle]["y"])]
                for vehicle in idle
            }
            chosen = min(idle, key=lambda vehicle: (distances[vehicle], vehicle))
            index = len(assigned)
            if index >= len(decisions):
                raise ValueError(f"t={tick}: missing dispatch for {task.id}")
            decision = decisions[index]
            expected = (index + 1, tick, task.id, task.release_time, chosen, distances[chosen], distances)
            actual = (int(decision["sequence"]), int(decision["time"]), decision["task_id"],
                      int(decision["release_time"]), decision["vehicle_id"], int(decision["pickup_distance"]),
                      json.loads(decision["idle_distances"]))
            if actual != expected:
                raise ValueError(f"Dispatch {index + 1}: expected t={tick}, {task.id} -> {chosen}, distances={distances}")
            assigned[task.id] = (chosen, tick)
            busy[chosen] = task.id
            idle.remove(chosen)
    if len(assigned) != len(decisions):
        raise ValueError("Unexpected extra dispatch records")
    for task_id, row in ledger.items():
        vehicle = row["vehicle_id"] or None
        tick = None if row["assigned_at"] in (None, "") else int(row["assigned_at"])
        finish = None if row["completed_at"] in (None, "") else int(row["completed_at"])
        if (vehicle, tick) != assigned.get(task_id, (None, None)) or finish != completed.get(task_id):
            raise ValueError(f"{task_id}: tasks.csv disagrees with the dispatch or trajectory")
    return {"dispatch_ok": True, "checked_dispatches": len(assigned)}
