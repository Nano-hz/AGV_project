"""根据输入和逐帧轨迹回放派单与取放货。

重建各时刻的待办队列和空闲车辆，复算候选评分与任务完成时间，再与保存的日志比对。
"""

from collections import deque
import json

from ..algorithms.planner import distances_to
from ..algorithms.space_time import ReservationTable, plan_task


def _position(row):
    return int(row["x"]), int(row["y"])


def _observe_service(scenario, task, record, previous, row, tick):
    """用相邻轨迹帧核对移动和服务动作，并重建取放货时刻。"""
    action = row["action"]
    position = _position(row)
    if action not in ("move", "wait", "pickup", "dropoff") or (action == "move") != (position != _position(previous)):
        raise ValueError(f"t={tick}: invalid movement/action for {task.id}")

    for service, started, finished, goal, duration in (
        ("pickup", "pickup_started_at", "picked_at", tuple(task.pickup), scenario.pickup_steps),
        ("dropoff", "dropoff_started_at", "completed_at", tuple(task.delivery), scenario.dropoff_steps),
    ):
        if action != service:
            if started in record and finished not in record:
                raise ValueError(f"t={tick}: interrupted {service} for {task.id}")
            continue
        if position != goal or finished in record or (service == "dropoff" and "picked_at" not in record):
            raise ValueError(f"t={tick}: invalid {service} for {task.id}")
        # 当前轨迹帧记录动作结束时刻，因此首个服务动作从 tick - 1 开始。
        first = record.setdefault(started, tick - 1)
        if tick - first == duration:
            record[finished] = tick

    status = "completed" if "completed_at" in record else "picked_up" if "picked_at" in record else "assigned"
    if row["task_status"] != status:
        raise ValueError(f"t={tick}: status for {task.id} disagrees with its service actions")
    return status


def _completion_choice(scenario, tick, pending, idle, frame, distances, reservations):
    """从轨迹中的车辆位置重新计算 B1/P 候选分数及排序。"""
    candidates, ranks = [], []
    for task in pending:
        pickup, delivery = tuple(task.pickup), tuple(task.delivery)
        for vehicle in sorted(idle):
            start = _position(frame[vehicle])
            static = tick + distances[pickup][start] + distances[delivery][pickup] + scenario.pickup_steps + scenario.dropoff_steps
            finish, steps, reason = static, None, None
            if reservations is not None:
                steps, reason = plan_task(scenario, task, start, tick, reservations.others(vehicle))
                finish = tick + len(steps) if steps is not None else None
            candidates.append({
                "task_id": task.id, "vehicle_id": vehicle, "static_finish": static,
                "estimated_finish": finish, "unavailable_reason": reason,
            })
            if finish is not None:
                rank = (finish, task.release_time, task.id, vehicle)
                ranks.append((rank, task, vehicle, steps))
    if not ranks:
        return None
    rank, task, vehicle, steps = min(ranks, key=lambda option: option[0])
    return task, vehicle, rank[0], steps, candidates


def audit_dispatch(scenario, trace, decisions, task_rows, last_tick):
    """逐时刻复核派单，并从实际服务动作复算完成数和完成时间。"""
    frames = [{} for _ in range(last_tick + 1)]
    for row in trace:
        frames[int(row["time"])][row["vehicle_id"]] = row

    tasks = {task.id: task for task in scenario.tasks}
    ledger = {row["task_id"]: row for row in task_rows}
    if ledger.keys() != tasks.keys() or len(task_rows) != len(tasks):
        raise ValueError("Task ledger must contain one row per input task")
    future = deque(sorted(tasks.values(), key=lambda task: (task.release_time, task.id)))
    pending = []
    targets = {tuple(cell) for task in tasks.values() for cell in (task.pickup, task.delivery)}
    distance_maps = {cell: distances_to(scenario.grid, cell) for cell in targets}
    policy = scenario.dispatch_policy
    reservations = ReservationTable({v.id: tuple(v.start) for v in scenario.vehicles}) if policy == "P" else None
    busy, observed, completed = {}, {}, {}
    for tick, frame in enumerate(frames):
        # 先从本帧确认哪些车刚刚放货，再决定当前时刻哪些车可以领单。
        for vehicle, row in frame.items():
            if vehicle not in busy:
                if row["phase"] != "idle" or row["action"] not in ("initial", "wait"):
                    raise ValueError(f"t={tick}: {vehicle} acted without a dispatch")
                if tick and _position(row) != _position(frames[tick - 1][vehicle]):
                    raise ValueError(f"t={tick}: idle {vehicle} changed cells")
                continue
            task_id = busy[vehicle]
            if row["task_id"] != task_id:
                raise ValueError(f"t={tick}: trajectory for {vehicle} must show {task_id}")
            status = _observe_service(scenario, tasks[task_id], observed[task_id], frames[tick - 1][vehicle], row, tick)
            if status == "completed":
                completed[task_id] = tick
                del busy[vehicle]
        if tick == last_tick:
            break
        while future and future[0].release_time <= tick:
            pending.append(future.popleft())
        idle = frame.keys() - busy.keys()
        while idle and pending:
            if policy == "B0":
                task = pending[0]
                distances = {v: distance_maps[tuple(task.pickup)][_position(frame[v])] for v in idle}
                chosen = min(idle, key=lambda vehicle: (distances[vehicle], vehicle))
            else:
                choice = _completion_choice(scenario, tick, pending, idle, frame, distance_maps, reservations)
                if choice is None:
                    break
                task, chosen, finish, steps, candidates = choice
                distances = {v: distance_maps[tuple(task.pickup)][_position(frame[v])] for v in idle}

            index = len(observed)
            if index >= len(decisions):
                raise ValueError(f"t={tick}: missing dispatch for {task.id}")
            decision = decisions[index]
            expected = (index + 1, tick, task.id, task.release_time, chosen, distances[chosen], distances)
            actual = (int(decision["sequence"]), int(decision["time"]), decision["task_id"], int(decision["release_time"]),
                      decision["vehicle_id"], int(decision["pickup_distance"]), json.loads(decision["idle_distances"]))
            if actual != expected:
                raise ValueError(f"Dispatch {index + 1}: expected t={tick}, {task.id} -> {chosen}, distances={distances}")
            if policy != "B0":
                if int(decision["estimated_finish"]) != finish or json.loads(decision["candidates"]) != candidates:
                    raise ValueError(f"Dispatch {index + 1}: candidate completion estimates disagree")
            if reservations is not None:
                # P 逐单重建预约，并逐步核对中选路线是否按计划执行。
                reservations.commit(chosen, tick, _position(frame[chosen]), steps)
                for offset, step in enumerate(steps, 1):
                    if tick + offset > last_tick:
                        raise ValueError(f"Dispatch {index + 1}: planned route extends past the trace")
                    row = frames[tick + offset][chosen]
                    if _position(row) != step.end or row["action"] != step.action:
                        raise ValueError(f"Dispatch {index + 1}: P did not execute the selected route")
            observed[task.id] = {"vehicle_id": chosen, "assigned_at": tick}
            busy[chosen] = task.id
            idle.remove(chosen)
            pending.remove(task)

    if len(observed) != len(decisions):
        raise ValueError("Unexpected extra dispatch records")
    # 用动作重建的任务历程核对任务表，再从重建结果计算整轮指标。
    for task_id, row in ledger.items():
        record = observed.get(task_id, {})
        task = tasks[task_id]
        if task_id in completed:
            status = "completed"
        elif "picked_at" in record:
            status = "picked_up"
        elif record:
            status = "assigned"
        else:
            status = "pending" if task.release_time < last_tick else "unreleased"
        if int(row["release_time"]) != task.release_time or row["status"] != status:
            raise ValueError(f"{task_id}: tasks.csv has incorrect release time or status")
        if (row["vehicle_id"] or None) != record.get("vehicle_id"):
            raise ValueError(f"{task_id}: tasks.csv disagrees with the assigned vehicle")
        for field in ("assigned_at", "pickup_started_at", "picked_at", "dropoff_started_at", "completed_at", "flow_time"):
            expected = record.get(field)
            if field == "flow_time" and task_id in completed:
                expected = completed[task_id] - task.release_time
            actual = None if row[field] in (None, "") else int(row[field])
            if actual != expected:
                raise ValueError(f"{task_id}: tasks.csv has incorrect {field}")

    all_completed = len(completed) == len(tasks)
    return {
        "dispatch_ok": True,
        "checked_dispatches": len(observed),
        "recomputed_completed_tasks": len(completed),
        "recomputed_makespan": max(completed.values()) if all_completed else None,
        "recomputed_mean_flow_time": (
            sum(tick - tasks[task_id].release_time for task_id, tick in completed.items()) / len(tasks)
            if all_completed else None
        ),
    }
