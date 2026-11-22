"""Behavioral checks for physical time, valid routing, and saved evidence."""

from collections import deque
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from warehouse_sim.algorithms.planner import shortest_path
from warehouse_sim.models import GridMap, Scenario, TaskSpec, VehicleSpec, load_scenario
from warehouse_sim.output import read_csv, save_result
from warehouse_sim.simulation.simulator import run

ROOT = Path(__file__).resolve().parents[1]


def tiny(**parameters):
    return Scenario("hand_checked", GridMap("line", ("#######", "#P.U.D#", "#######")), (VehicleSpec("A", (1, 1)),), (TaskSpec("T", 0, (3, 1), (5, 1)),), **parameters)


def bfs_distance(grid, start, goal):
    queue, seen = deque([(start, 0)]), {start}
    while queue:
        here, length = queue.popleft()
        if here == goal:
            return length
        # Independent neighbor implementation for the shortest-path oracle.
        x, y = here
        for p in ((x, y - 1), (x - 1, y), (x, y + 1), (x + 1, y)):
            if grid.walkable(p) and p not in seen:
                seen.add(p)
                queue.append((p, length + 1))
    return None


class SimulationTests(unittest.TestCase):
    def test_hand_checked_timeline(self):
        result = run(tiny())
        self.assertEqual([r["action"] for r in result.trace], ["initial", "move", "move", "pickup", "move", "move", "dropoff"])
        self.assertEqual([r["x"] for r in result.trace], [1, 2, 3, 3, 4, 5, 5])
        self.assertEqual([r["loaded"] for r in result.trace], [0, 0, 0, 1, 1, 1, 0])
        self.assertEqual(result.task_rows[0]["picked_at"], 3)
        self.assertEqual(result.task_rows[0]["completed_at"], 6)
        self.assertEqual(result.summary["total_distance"], 4)
        self.assertEqual(result.summary["mean_flow_time"], 6)
        self.assertEqual(result.summary["total_service_steps"], 2)

    def test_release_time_and_flow_time(self):
        original = tiny()
        scenario = replace(original, tasks=(replace(original.tasks[0], release_time=3),))
        result = run(scenario)
        self.assertEqual(result.task_rows[0]["assigned_at"], 3)
        self.assertEqual(result.summary["makespan"], 9)
        self.assertEqual(result.summary["mean_flow_time"], 6)
        self.assertEqual(result.summary["total_wait_steps"], 3)
        self.assertTrue(all(r["x"] == 1 for r in result.trace[:4]))

    def test_service_duration_is_real_occupancy(self):
        result = run(tiny(pickup_steps=2, dropoff_steps=3))
        self.assertEqual(result.summary["makespan"], 9)
        self.assertEqual(result.summary["total_service_steps"], 5)
        self.assertEqual(result.task_rows[0]["picked_at"], 4)
        for before, after in zip(result.trace, result.trace[1:]):
            if after["action"] in ("pickup", "dropoff", "wait"):
                self.assertEqual((before["x"], before["y"]), (after["x"], after["y"]))

    def test_timeout_preserves_partial_task(self):
        result = run(tiny(max_steps=3))
        self.assertFalse(result.summary["success"])
        self.assertEqual(result.summary["failure_reason"], "max_steps_exceeded")
        self.assertEqual(result.task_rows[0]["status"], "picked_up")
        self.assertIsNone(result.summary["makespan"])
        self.assertIsNone(result.summary["mean_flow_time"])
        self.assertEqual(len(result.trace), 4)

    def test_completion_at_limit_is_success(self):
        self.assertTrue(run(tiny(max_steps=6)).summary["success"])

    def test_unreleased_task_at_timeout(self):
        original = tiny(max_steps=2)
        result = run(replace(original, tasks=(replace(original.tasks[0], release_time=9),)))
        self.assertEqual(result.task_rows[0]["status"], "unreleased")
        self.assertIsNone(result.task_rows[0]["assigned_at"])
        self.assertEqual(result.summary["total_wait_steps"], 2)

    def test_all_maps_match_independent_shortest_path(self):
        for path in sorted((ROOT / "instances").glob("single_*.json")):
            with self.subTest(instance=path.name):
                scenario = load_scenario(path)
                result = run(scenario)
                vehicle, task = scenario.vehicles[0], scenario.tasks[0]
                expected = bfs_distance(scenario.grid, vehicle.start, task.pickup) + bfs_distance(scenario.grid, task.pickup, task.delivery)
                self.assertTrue(result.summary["success"])
                self.assertEqual(result.summary["total_distance"], expected)
                self.assertEqual(result.summary["makespan"], expected + 2)
                self.assertEqual(result.summary["total_distance"] + result.summary["total_wait_steps"] + result.summary["total_service_steps"], result.summary["simulation_steps"])
                for before, after in zip(result.trace, result.trace[1:]):
                    self.assertTrue(scenario.grid.walkable((after["x"], after["y"])))
                    self.assertEqual(after["time"] - before["time"], 1)
                    self.assertLessEqual(abs(after["x"] - before["x"]) + abs(after["y"] - before["y"]), 1)

    def test_bottleneck_is_only_crossing(self):
        scenario = load_scenario(ROOT / "instances/single_bottleneck.json")
        self.assertEqual([y for y in range(20) if scenario.grid.walkable((10, y))], [10])
        self.assertIn((10, 10), [(r["x"], r["y"]) for r in run(scenario).trace])

    def test_deterministic_replay(self):
        first, second = run(tiny()), run(tiny())
        self.assertEqual(first.trace, second.trace)
        self.assertEqual(first.events, second.events)
        self.assertEqual(first.task_rows, second.task_rows)
        self.assertEqual({k: v for k, v in first.summary.items() if k != "runtime_seconds"}, {k: v for k, v in second.summary.items() if k != "runtime_seconds"})

    def test_saved_snapshot_is_self_contained(self):
        # Temporary evidence stays within project even on constrained hosts.
        temporary_root = ROOT / ".build"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temp:
            output = Path(temp) / "run"
            first = run(load_scenario(ROOT / "instances/single_wide.json"))
            save_result(first, output)
            second = run(load_scenario(output / "instance.json"))
            self.assertEqual(first.trace, second.trace)
            self.assertEqual(len(read_csv(output / "trajectory.csv")), len(first.trace))
            self.assertEqual(read_csv(output / "tasks.csv")[0]["status"], "completed")
            with self.assertRaises(FileExistsError):
                save_result(first, output)


class ValidationTests(unittest.TestCase):
    def test_disconnected_map_rejected(self):
        with self.assertRaisesRegex(ValueError, "connected"):
            GridMap("bad", ("#####", "#P#D#", "#####")).validate()

    def test_blocked_or_outside_endpoint_rejected(self):
        original = tiny()
        for start in ((0, 0), (99, 99)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                run(replace(original, vehicles=(VehicleSpec("A", start),)))

    def test_invalid_service_time_rejected(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run(tiny(pickup_steps=value))

    def test_duplicate_pickup_delivery_rejected(self):
        original = tiny()
        with self.assertRaisesRegex(ValueError, "different"):
            run(replace(original, tasks=(replace(original.tasks[0], delivery=(3, 1)),)))

    def test_vehicle_and_task_count_must_match(self):
        original = tiny()
        for scenario in (replace(original, vehicles=original.vehicles * 2), replace(original, tasks=original.tasks * 2)):
            with self.assertRaisesRegex(ValueError, "one fixed task each"):
                run(scenario)

    def test_astar_detour_and_unreachable(self):
        grid = GridMap("detour", ("#######", "#P#..D#", "#...###", "#######"))
        grid.validate()
        path = shortest_path(grid, (1, 1), (5, 1))
        self.assertEqual(len(path) - 1, 6)
        self.assertIsNone(shortest_path(grid, (0, 0), (5, 1)))
        isolated = GridMap("isolated", ("#####", "#P#D#", "#####"))
        self.assertIsNone(shortest_path(isolated, (1, 1), (3, 1)))
        self.assertEqual(shortest_path(grid, (1, 1), (1, 1)), [(1, 1)])


if __name__ == "__main__":
    unittest.main()
