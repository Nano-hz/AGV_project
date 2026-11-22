"""A* over position, time, and service progress with prioritized reservations."""

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count

from .models import Cell, Scenario, TaskSpec
from .planner import distances_to


@dataclass(frozen=True)
class Step:
    action: str
    end: Cell


@dataclass(frozen=True)
class Reservation:
    start_time: int
    positions: tuple[Cell, ...]

    def at(self, tick: int) -> Cell:
        index = min(max(0, tick - self.start_time), len(self.positions) - 1)
        return self.positions[index]

    def visits_from(self, cell: Cell, tick: int) -> bool:
        index = min(max(0, tick - self.start_time), len(self.positions) - 1)
        return cell in self.positions[index:]


class ReservationTable:
    def __init__(self, starts: dict[str, Cell]):
        self.routes = {vehicle: Reservation(0, (cell,)) for vehicle, cell in starts.items()}

    def commit(self, vehicle: str, tick: int, start: Cell, steps: list[Step]):
        self.routes[vehicle] = Reservation(tick, (start, *(step.end for step in steps)))

    def others(self, vehicle: str) -> tuple[Reservation, ...]:
        return tuple(route for owner, route in self.routes.items() if owner != vehicle)


def can_step(others: tuple[Reservation, ...], start: Cell, end: Cell, tick: int) -> bool:
    """Check the vertex at t+1 and the reverse edge during [t,t+1)."""
    for route in others:
        before, after = route.at(tick), route.at(tick + 1)
        if end == after or (start == after and end == before):
            return False
    return True


def plan_task(scenario: Scenario, task: TaskSpec, start: Cell, tick: int, others: tuple[Reservation, ...]) -> tuple[list[Step] | None, str | None]:
    """Return a full pick/deliver route or the reason planning was deferred."""
    pickup, delivery = tuple(task.pickup), tuple(task.delivery)
    # A finished vehicle occupies its delivery cell for the rest of the run.
    if any(route.positions[-1] == delivery for route in others):
        return None, "delivery_reserved_for_stop"
    if any(route.at(tick) == start for route in others):
        return None, "start_occupied"
    blocked = {route.positions[-1] for route in others if tick >= route.start_time + len(route.positions) - 1}
    to_pickup = distances_to(scenario.grid, pickup, blocked)
    to_delivery = distances_to(scenario.grid, delivery, blocked)
    if start not in to_pickup or pickup not in to_delivery:
        return None, "stationary_vehicle_blocks_route"
    pickup_steps = scenario.pickup_steps
    services = pickup_steps + scenario.dropoff_steps

    def estimate(cell, progress):
        remaining = services - progress
        if progress < pickup_steps:
            return to_pickup.get(cell, float("inf")) + to_delivery[pickup] + remaining
        return to_delivery.get(cell, float("inf")) + remaining

    # A service in progress can only continue in place until completed.
    def actions(cell, progress):
        goal = pickup if progress < pickup_steps else delivery
        if cell == goal:
            yield Step("pickup" if progress < pickup_steps else "dropoff", cell), progress + 1
        if progress in (0, pickup_steps):
            for neighbor in scenario.grid.neighbors(cell):
                yield Step("move", neighbor), progress
            yield Step("wait", cell), progress

    initial = (start, tick, 0)
    cutoff = scenario.max_steps
    if tick + estimate(start, 0) > cutoff:
        return None, "insufficient_time_remaining"
    order = count()
    frontier = [(tick + estimate(start, 0), next(order), initial)]
    parents = {initial: None}
    while frontier:
        _, _, state = heappop(frontier)
        cell, time, progress = state
        if progress == services:
            steps = []
            while parents[state] is not None:
                state, step = parents[state]
                steps.append(step)
            return list(reversed(steps)), None
        for step, next_progress in actions(cell, progress):
            arrival = time + 1
            score = arrival + estimate(step.end, next_progress)
            successor = (step.end, arrival, next_progress)
            if score > cutoff or successor in parents or not can_step(others, cell, step.end, time):
                continue
            if next_progress == services and any(route.visits_from(step.end, arrival) for route in others):
                continue
            parents[successor] = (state, step)
            heappush(frontier, (score, next(order), successor))
    return None, "no_route_within_step_limit"
