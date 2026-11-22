"""Select a task and vehicle using B0, B1, or P."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..models import Cell, Scenario, TaskSpec
from .planner import distances_to, shortest_path
from .space_time import ReservationTable, Step, plan_task


@dataclass
class Candidate:
    task: TaskSpec
    vehicle_id: str
    static_finish: int
    estimated_finish: int | None
    steps: list[Step] | None = None
    unavailable_reason: str | None = None

    def log(self):
        return {
            "task_id": self.task.id, "vehicle_id": self.vehicle_id,
            "static_finish": self.static_finish, "estimated_finish": self.estimated_finish,
            "unavailable_reason": self.unavailable_reason,
        }


class CompletionScorer:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        targets = {tuple(cell) for task in scenario.tasks for cell in (task.pickup, task.delivery)}
        self.distances = {cell: distances_to(scenario.grid, cell) for cell in targets}

    def candidates(self, tick, pending, positions, reservations):
        scenario = self.scenario
        for task in pending:
            pickup, delivery = tuple(task.pickup), tuple(task.delivery)
            service_and_delivery = scenario.pickup_steps + self.distances[delivery][pickup] + scenario.dropoff_steps
            for vehicle_id, start in sorted(positions.items()):
                static_finish = tick + self.distances[pickup][start] + service_and_delivery
                if scenario.dispatch_policy == "B1":
                    yield Candidate(task, vehicle_id, static_finish, static_finish)
                else:
                    steps, reason = plan_task(scenario, task, start, tick, reservations.others(vehicle_id))
                    finish = tick + len(steps) if steps is not None else None
                    yield Candidate(task, vehicle_id, static_finish, finish, steps, reason)


@dataclass
class DispatchChoice:
    task: TaskSpec
    vehicle_id: str
    pickup_distances: dict[str, int]
    steps: list[Step] | None = None
    estimated_finish: int | None = None
    candidates: tuple[Candidate, ...] = ()


class Dispatcher:
    """Evaluate candidates without assigning tasks or changing the reservations."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.completion = CompletionScorer(scenario) if scenario.dispatch_policy in ("B1", "P") else None

    def choose(
        self,
        tick: int,
        pending: Iterable[TaskSpec],
        positions: Mapping[str, Cell],
        reservations: ReservationTable,
    ) -> DispatchChoice | None:
        if self.completion is None:
            task = next(iter(pending))
            distances = {}
            for vehicle_id, position in positions.items():
                path = shortest_path(self.scenario.grid, position, tuple(task.pickup))
                if path is None:
                    raise RuntimeError("Validated map has no route to pickup")
                distances[vehicle_id] = len(path) - 1
            chosen = min(distances, key=lambda vehicle_id: (distances[vehicle_id], vehicle_id))
            return DispatchChoice(task, chosen, distances)

        candidates = tuple(self.completion.candidates(tick, pending, positions, reservations))
        feasible = (candidate for candidate in candidates if candidate.estimated_finish is not None)
        best = min(feasible, key=lambda candidate: (
            candidate.estimated_finish, candidate.task.release_time, candidate.task.id, candidate.vehicle_id,
        ), default=None)
        if best is None:
            return None

        pickup_distances = self.completion.distances[tuple(best.task.pickup)]
        distances = {vehicle_id: pickup_distances[position] for vehicle_id, position in positions.items()}
        return DispatchChoice(best.task, best.vehicle_id, distances, best.steps, best.estimated_finish, candidates)
