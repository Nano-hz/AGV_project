"""The main factorial experiment and its paired, repeatable inputs."""

from dataclasses import dataclass
from pathlib import Path
from random import Random

from .models import GridMap, Scenario, TaskSpec, VehicleSpec, read_json


PICKUPS = {
    "wide": ((7, 4), (13, 4), (7, 15), (13, 15)),
    "narrow": ((7, 4), (17, 4), (7, 12), (17, 12)),
    "bottleneck": ((7, 4), (16, 4), (7, 14), (16, 14)),
}
VEHICLE_COUNTS = (2, 4)
TASK_COUNTS = (8, 16, 24)
SEEDS = tuple(range(10))
MAX_STEPS = 1000


@dataclass(frozen=True)
class Case:
    layout: str
    vehicle_count: int
    task_count: int
    seed: int

    @property
    def id(self):
        return f"{self.layout}_v{self.vehicle_count}_n{self.task_count:02d}_s{self.seed:02d}"


def cases(seeds):
    for layout in PICKUPS:
        for vehicles in VEHICLE_COUNTS:
            for tasks in TASK_COUNTS:
                for seed in seeds:
                    yield Case(layout, vehicles, tasks, seed)


def read_grids(maps_dir):
    return {name: GridMap.from_dict(read_json(Path(maps_dir) / f"{name}.json")) for name in PICKUPS}


def make_input(case, grid, max_steps=MAX_STEPS):
    pickups = PICKUPS[case.layout]
    starts = grid.cells("P")
    deliveries = grid.cells("D")
    if len(starts) != 4 or len(deliveries) != 4 or not set(pickups) <= set(grid.cells("U")):
        raise ValueError(f"The fixed bays for {case.layout} do not match the map")
    start_indexes = (0, 3) if case.vehicle_count == 2 else range(4)
    vehicles = tuple(VehicleSpec(f"AGV-{index + 1:02d}", starts[index]) for index in start_indexes)
    rng = Random(case.seed)
    tasks = tuple(
        TaskSpec(f"T{i + 1:03d}", 0, pickups[rng.randrange(4)], deliveries[rng.randrange(4)])
        for i in range(case.task_count)
    )
    scenario = Scenario(case.id, grid, vehicles, tasks, seed=case.seed, max_steps=max_steps, dispatch_policy="B0")
    scenario.validate()
    return scenario
