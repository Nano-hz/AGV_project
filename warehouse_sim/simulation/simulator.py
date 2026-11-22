"""Advance all vehicles together by one action per discrete tick."""

from collections import deque
from dataclasses import dataclass, field
import json
from time import perf_counter

from ..algorithms.dispatch import Dispatcher
from ..algorithms.space_time import ReservationTable, Step, plan_static_task, plan_task
from ..models import AUTO_POLICIES, Cell, Scenario, TaskSpec, VehicleSpec
from .collisions import audit_trajectory


@dataclass
class VehicleState:
    vehicle: VehicleSpec
    task: TaskSpec | None = None
    position: Cell = field(init=False)
    task_row: dict | None = None
    steps: deque[Step] = field(default_factory=deque)
    phase: str = "idle"
    loaded: bool = False
    distance: int = 0
    wait_steps: int = 0
    service_steps: int = 0

    def __post_init__(self):
        self.position = tuple(self.vehicle.start)

    @property
    def vehicle_id(self):
        return self.vehicle.id

    @property
    def status(self):
        return self.task_row["status"] if self.task_row is not None else "idle"

    def event(self, tick, kind):
        return {
            "time": tick, "event": kind, "vehicle_id": self.vehicle_id,
            "task_id": self.task.id if self.task else "", "x": self.position[0], "y": self.position[1],
        }

    def snapshot(self, tick, action):
        return {
            "time": tick, "vehicle_id": self.vehicle_id, "x": self.position[0], "y": self.position[1],
            "phase": self.phase, "task_id": self.task.id if self.task_row and self.task_row["assigned_at"] is not None else "",
            "task_status": self.status, "loaded": int(self.loaded), "action": action,
            "distance": self.distance, "wait_steps": self.wait_steps, "service_steps": self.service_steps,
        }

    def advance(self, tick, events):
        step = self.steps.popleft() if self.steps else Step("wait", self.position)
        following = self.steps[0].action if self.steps else None
        if step.action == "move":
            self.position = step.end
            self.distance += 1
        elif step.action == "wait":
            self.wait_steps += 1
        else:
            self.service_steps += 1
            key = step.action + "_started_at"
            if self.task_row[key] is None:
                self.task_row[key] = tick
                events.append(self.event(tick, step.action + "_started"))
            if following != step.action:
                if step.action == "pickup":
                    self.task_row.update(picked_at=tick + 1, status="picked_up")
                    self.loaded, self.phase = True, "to_delivery"
                    events.append(self.event(tick + 1, "pickup_completed"))
                else:
                    self.task_row.update(completed_at=tick + 1, flow_time=tick + 1 - self.task.release_time, status="completed")
                    self.loaded, self.phase = False, "idle"
                    events.append(self.event(tick + 1, "task_completed"))
        if following in ("pickup", "dropoff") and self.phase != following:
            self.phase = following
            events.append(self.event(tick + 1, "arrived_" + following))
        return self.snapshot(tick + 1, step.action)

    def assign(self, task, row, tick, events):
        self.task, self.task_row = task, row
        row.update(vehicle_id=self.vehicle_id, assigned_at=tick, status="assigned")
        self.phase = "to_pickup"
        events.append(self.event(tick, "task_assigned"))


def _task_row(task):
    return {
        "task_id": task.id, "release_time": task.release_time,
        "pickup_x": task.pickup[0], "pickup_y": task.pickup[1],
        "delivery_x": task.delivery[0], "delivery_y": task.delivery[1],
        "vehicle_id": None, "assigned_at": None, "pickup_started_at": None,
        "picked_at": None, "dropoff_started_at": None, "completed_at": None,
        "flow_time": None, "status": "unreleased",
    }


def _queue_event(task, tick, kind):
    return {"time": tick, "event": kind, "vehicle_id": "", "task_id": task.id,
            "x": task.pickup[0], "y": task.pickup[1]}


@dataclass
class SimulationResult:
    scenario: Scenario
    trace: list[dict]
    events: list[dict]
    task_rows: list[dict]
    summary: dict
    dispatches: list[dict] | None = None


def _reserve(scenario, state, tick, reservations, events, steps=None):
    if reservations is None:
        steps = plan_static_task(scenario, state.task, state.position)
    else:
        if steps is None:
            steps, reason = plan_task(scenario, state.task, state.position, tick, reservations.others(state.vehicle_id))
            if steps is None:
                events.append({**state.event(tick, "plan_unavailable"), "reason": reason})
                return
        reservations.commit(state.vehicle_id, tick, state.position, steps)
        events.append(state.event(tick, "plan_committed"))
    state.steps.extend(steps)


def _dispatch(scenario, tick, pending, states, rows, reservations, events, dispatches, dispatcher):
    idle = {state.vehicle_id: state for state in states if state.phase == "idle"}
    while pending and idle:
        positions = {vehicle_id: state.position for vehicle_id, state in idle.items()}
        choice = dispatcher.choose(tick, pending, positions, reservations)
        if choice is None:
            # Leave all tasks pending and reconsider after advancing the clock.
            events.append({**_queue_event(pending[0], tick, "dispatch_deferred"), "reason": "no_feasible_pair"})
            break

        task, chosen = choice.task, choice.vehicle_id
        pending.remove(task)
        state = idle.pop(chosen)
        state.assign(task, rows[task.id], tick, events)
        record = {
            "sequence": len(dispatches) + 1, "time": tick, "task_id": task.id,
            "release_time": task.release_time, "vehicle_id": chosen,
            "pickup_distance": choice.pickup_distances[chosen],
            "idle_distances": json.dumps(choice.pickup_distances, ensure_ascii=False, sort_keys=True),
        }
        if choice.estimated_finish is not None:
            record["estimated_finish"] = choice.estimated_finish
            record["candidates"] = json.dumps([candidate.log() for candidate in choice.candidates], ensure_ascii=False)
        dispatches.append(record)
        _reserve(scenario, state, tick, reservations, events, choice.steps)


def run(scenario: Scenario) -> SimulationResult:
    scenario.validate()
    started = perf_counter()
    multi = len(scenario.vehicles) > 1
    auto = scenario.dispatch_policy in AUTO_POLICIES
    dispatcher = Dispatcher(scenario) if auto else None
    states = [VehicleState(vehicle) for vehicle in sorted(scenario.vehicles, key=lambda vehicle: vehicle.id)]
    tasks = sorted(scenario.tasks, key=lambda task: (task.release_time, task.id) if auto else (task.vehicle_id or "", task.id))
    rows = {task.id: _task_row(task) for task in tasks}
    if not auto:
        for state, task in zip(states, tasks):
            state.task, state.task_row = task, rows[task.id]
    future, pending = deque(tasks), deque()
    dispatches = [] if auto else None
    reservations = ReservationTable({state.vehicle_id: state.position for state in states}) if multi else None
    trace = [state.snapshot(0, "initial") for state in states]
    events = []
    time = 0

    while time < scenario.max_steps and any(row["status"] != "completed" for row in rows.values()):
        if auto:
            while future and future[0].release_time <= time:
                task = future.popleft()
                rows[task.id]["status"] = "pending"
                pending.append(task)
                events.append(_queue_event(task, time, "task_released"))
        else:
            for state in states:
                if state.status == "unreleased" and time >= state.task.release_time:
                    events.append(state.event(time, "task_released"))
                    state.assign(state.task, state.task_row, time, events)

        for state in states:
            if state.status == "assigned" and not state.steps:
                _reserve(scenario, state, time, reservations, events)
        if auto:
            _dispatch(scenario, time, pending, states, rows, reservations, events, dispatches, dispatcher)

        for state in states:
            trace.append(state.advance(time, events))
        time += 1

    for state in states:
        if state.distance + state.wait_steps + state.service_steps != time:
            raise RuntimeError("Time accounting invariant violated")
        if state.task is not None and state.status != "completed":
            events.append(state.event(time, "max_steps_exceeded"))
    if auto:
        for task in (*pending, *future):
            events.append(_queue_event(task, time, "max_steps_exceeded"))
    events.sort(key=lambda item: item["time"])
    if multi:
        for event in events:
            event.setdefault("reason", "")

    audit = audit_trajectory(scenario, trace, time)
    completed = [row for row in rows.values() if row["status"] == "completed"]
    all_completed = len(completed) == len(rows)
    failure = None if all_completed else "max_steps_exceeded"
    if audit["conflict_count"]:
        failure = "trajectory_conflict"
    summary = {
        "schema_version": 1, "stage": 4 if scenario.dispatch_policy in ("B1", "P") else (3 if auto else (2 if multi else 1)),
        "method": scenario.dispatch_policy if auto else ("fixed_assignment_space_time_astar" if multi else "single_agv_static_astar"),
        "instance": scenario.name, "map": scenario.grid.name, "seed": scenario.seed,
        "vehicle_count": len(states), "task_count": len(rows), "completed_tasks": len(completed),
        "success": failure is None, "failure_reason": failure, "completion_rate": len(completed) / len(rows),
        "simulation_steps": time,
        "mean_flow_time": (sum(row["flow_time"] for row in completed) / len(completed)) if all_completed else None,
        "makespan": max(row["completed_at"] for row in completed) if all_completed else None,
        "total_distance": sum(state.distance for state in states),
        "total_wait_steps": sum(state.wait_steps for state in states),
        "total_service_steps": sum(state.service_steps for state in states),
        "conflict_count": audit["conflict_count"],
        "conflict_check_scope": "all_vehicle_pairs" if multi else "single_vehicle_only",
        "runtime_seconds": perf_counter() - started,
    }
    if multi:
        summary.update(
            vertex_conflicts=audit["vertex_conflicts"], edge_swap_conflicts=audit["edge_swap_conflicts"],
            planning_failures=sum(event["event"] == "plan_unavailable" for event in events),
        )
    elif all_completed:
        summary["mean_flow_time"] = completed[0]["flow_time"]
    return SimulationResult(scenario, trace, events, list(rows.values()), summary, dispatches)
