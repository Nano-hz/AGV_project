"""用 B0、B1 或 P 选择待办任务和空闲车辆。

B0 优先队首任务，B1 比较各组合的静态预计完工时刻，P 根据预约试算可行路线。
模块返回派单选择和评分，由仿真层更新任务队列并提交路线。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..models import Cell, Scenario, TaskSpec
from .planner import distances_to, shortest_path
from .space_time import ReservationTable, Step, plan_task


@dataclass
class Candidate:
    """一个车任务组合的评分、试算路线和不可行原因。"""

    task: TaskSpec
    vehicle_id: str
    static_finish: int
    estimated_finish: int | None
    steps: list[Step] | None = None
    unavailable_reason: str | None = None

    def log(self):
        """提取派单日志所需的字段。"""
        return {
            "task_id": self.task.id, "vehicle_id": self.vehicle_id,
            "static_finish": self.static_finish, "estimated_finish": self.estimated_finish,
            "unavailable_reason": self.unavailable_reason,
        }


class CompletionScorer:
    """缓存静态距离表，并用它为 B1 和 P 计算候选完工时刻。"""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        targets = {tuple(cell) for task in scenario.tasks for cell in (task.pickup, task.delivery)}
        self.distances = {cell: distances_to(scenario.grid, cell) for cell in targets}

    def candidates(self, tick, pending, positions, reservations):
        """枚举每个待办任务与每辆空闲车的组合，并计算该策略下的分数。"""
        scenario = self.scenario
        for task in pending:
            pickup, delivery = tuple(task.pickup), tuple(task.delivery)
            service_and_delivery = scenario.pickup_steps + self.distances[delivery][pickup] + scenario.dropoff_steps
            for vehicle_id, start in sorted(positions.items()):
                static_finish = tick + self.distances[pickup][start] + service_and_delivery
                if scenario.dispatch_policy == "B1":
                    yield Candidate(task, vehicle_id, static_finish, static_finish)
                else:
                    # P 在评分时试算完整路线，因此会把等待和绕行计入完成时刻。
                    steps, reason = plan_task(scenario, task, start, tick, reservations.others(vehicle_id))
                    finish = tick + len(steps) if steps is not None else None
                    yield Candidate(task, vehicle_id, static_finish, finish, steps, reason)


@dataclass
class DispatchChoice:
    """交给仿真层的派单选择，P 同时携带中选的路线。"""

    task: TaskSpec
    vehicle_id: str
    pickup_distances: dict[str, int]
    steps: list[Step] | None = None
    estimated_finish: int | None = None
    candidates: tuple[Candidate, ...] = ()


class Dispatcher:
    """只根据队列、空闲车位置和当前预约生成派单选择。"""

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
        """从非空队列和空闲车集合选出一组，P 无可行组合时返回 None。"""
        if self.completion is None:
            # 仿真层已按发布时间和任务编号排列队列，B0 只给队首任务选车。
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
        # 同一预计完成时刻依次按发布时刻、任务编号和车辆编号打平。
        best = min(feasible, key=lambda candidate: (
            candidate.estimated_finish, candidate.task.release_time, candidate.task.id, candidate.vehicle_id,
        ), default=None)
        if best is None:
            return None

        pickup_distances = self.completion.distances[tuple(best.task.pickup)]
        distances = {vehicle_id: pickup_distances[position] for vehicle_id, position in positions.items()}
        return DispatchChoice(best.task, best.vehicle_id, distances, best.steps, best.estimated_finish, candidates)
