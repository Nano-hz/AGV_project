"""任务路线规划与预约表。

单车模式拼接两段静态路线与取放货动作。多车模式在位置、时刻和服务进度上搜索，
根据其他车辆已提交的路线判断哪些动作可行。
"""

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count

from ..models import Cell, Scenario, TaskSpec
from .planner import distances_to, shortest_path


@dataclass(frozen=True)
class Step:
    """一个时间步的动作与动作完成后的格子。"""

    action: str
    end: Cell


def plan_static_task(scenario: Scenario, task: TaskSpec, start: Cell) -> list[Step]:
    """拼接去取货、原地取货、去送达和原地放货四段动作。"""
    pickup, delivery = tuple(task.pickup), tuple(task.delivery)
    first = shortest_path(scenario.grid, start, pickup)
    second = shortest_path(scenario.grid, pickup, delivery)
    if first is None or second is None:
        raise RuntimeError("Validated map has no static route")
    return [
        *(Step("move", cell) for cell in first[1:]),
        *(Step("pickup", pickup) for _ in range(scenario.pickup_steps)),
        *(Step("move", cell) for cell in second[1:]),
        *(Step("dropoff", delivery) for _ in range(scenario.dropoff_steps)),
    ]


@dataclass(frozen=True)
class Reservation:
    """一辆车的预约位置序列，起止位置向路线两端延伸。"""

    start_time: int
    positions: tuple[Cell, ...]

    def at(self, tick: int) -> Cell:
        """查询某时刻的占用格。路线结束后继续占用终点。"""
        index = min(max(0, tick - self.start_time), len(self.positions) - 1)
        return self.positions[index]

    def visits_from(self, cell: Cell, tick: int) -> bool:
        """判断该车从指定时刻起是否会经过或停在给定格子。"""
        index = min(max(0, tick - self.start_time), len(self.positions) - 1)
        return cell in self.positions[index:]


class ReservationTable:
    """按车辆编号保存最新承诺路线，尚未出发时预约起始格。"""

    def __init__(self, starts: dict[str, Cell]):
        self.routes = {vehicle: Reservation(0, (cell,)) for vehicle, cell in starts.items()}

    def commit(self, vehicle: str, tick: int, start: Cell, steps: list[Step]):
        """用当前格与新路线的每步终点更新该车的预约。"""
        self.routes[vehicle] = Reservation(tick, (start, *(step.end for step in steps)))

    def others(self, vehicle: str) -> tuple[Reservation, ...]:
        """取出其他车辆的预约，供当前车辆规划。"""
        return tuple(route for owner, route in self.routes.items() if owner != vehicle)


def can_step(others: tuple[Reservation, ...], start: Cell, end: Cell, tick: int) -> bool:
    """同时检查下一时刻的同格占用和这一步的对向交换。"""
    for route in others:
        before, after = route.at(tick), route.at(tick + 1)
        if end == after or (start == after and end == before):
            return False
    return True


def plan_task(scenario: Scenario, task: TaskSpec, start: Cell, tick: int, others: tuple[Reservation, ...]) -> tuple[list[Step] | None, str | None]:
    """在当前预约下搜索完整取送路线，返回动作序列或规划失败原因。"""
    pickup, delivery = tuple(task.pickup), tuple(task.delivery)
    # 预约终点持续占用，直到该车提交新路线并离开。
    if any(route.positions[-1] == delivery for route in others):
        return None, "delivery_reserved_for_stop"
    if any(route.at(tick) == start for route in others):
        return None, "start_occupied"
    # 已走完路线的车视为静态障碍，仍在行驶的车按各时刻预约检查。
    blocked = {route.positions[-1] for route in others if tick >= route.start_time + len(route.positions) - 1}
    to_pickup = distances_to(scenario.grid, pickup, blocked)
    to_delivery = distances_to(scenario.grid, delivery, blocked)
    if start not in to_pickup or pickup not in to_delivery:
        return None, "stationary_vehicle_blocks_route"
    pickup_steps = scenario.pickup_steps
    services = pickup_steps + scenario.dropoff_steps

    def estimate(cell, progress):
        # 静态剩余路程加剩余服务时间是下界，动态预约造成的额外用时由搜索体现。
        remaining = services - progress
        if progress < pickup_steps:
            return to_pickup.get(cell, float("inf")) + to_delivery[pickup] + remaining
        return to_delivery.get(cell, float("inf")) + remaining

    def actions(cell, progress):
        # 到达对应格后可开始服务，开始后须在原地连续执行到完成。
        goal = pickup if progress < pickup_steps else delivery
        if cell == goal:
            yield Step("pickup" if progress < pickup_steps else "dropoff", cell), progress + 1
        if progress in (0, pickup_steps):
            for neighbor in scenario.grid.neighbors(cell):
                yield Step("move", neighbor), progress
            yield Step("wait", cell), progress

    # 同一格在不同时刻的可用性可能不同，搜索状态还要保留服务进度。
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
            # 放货后会停留在送达格，须给其他车辆已预约的后续通行留出空间。
            if next_progress == services and any(route.visits_from(step.end, arrival) for route in others):
                continue
            parents[successor] = (state, step)
            heappush(frontier, (score, next(order), successor))
    return None, "no_route_within_step_limit"
