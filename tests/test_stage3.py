"""B0 dispatch, reuse of reservations across tasks, and independent verification."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warehouse_sim.models import GridMap, Scenario, TaskSpec, VehicleSpec, load_scenario
from warehouse_sim.output import read_csv, save_result
from warehouse_sim.simulation.dispatch_audit import audit_dispatch
from warehouse_sim.simulation.simulator import run


ROOT = Path(__file__).resolve().parents[1]


def automatic(name):
    fixed = load_scenario(ROOT / "instances" / name)
    return replace(fixed, dispatch_policy="B0", tasks=tuple(replace(t, vehicle_id=None) for t in fixed.tasks))


def verify(result, decisions=None):
    logs = result.dispatches if decisions is None else decisions
    return audit_dispatch(result.scenario, result.trace, logs, result.task_rows, result.summary["simulation_steps"])


class DispatchTests(unittest.TestCase):
    def test_mixed_releases_and_current_positions_for_second_round(self):
        scenario = load_scenario(ROOT / "instances/b0_wide_8.json")
        result = run(replace(scenario, tasks=tuple(reversed(scenario.tasks))))
        self.assertTrue(result.summary["success"])
        self.assertEqual(result.summary["conflict_count"], 0)
        self.assertEqual(verify(result)["checked_dispatches"], 8)
        self.assertEqual([d["task_id"] for d in result.dispatches],
                         ["T002", "T003", "T004", "T005", "T001", "T006", "T007", "T008"])
        first, second, third = result.dispatches[:3]
        self.assertEqual(json.loads(first["idle_distances"]), {"AGV-01": 18, "AGV-02": 9})
        self.assertEqual((first["vehicle_id"], second["vehicle_id"]), ("AGV-02", "AGV-01"))
        self.assertEqual(json.loads(second["idle_distances"]), {"AGV-01": 9})
        self.assertEqual((third["time"], json.loads(third["idle_distances"])), (34, {"AGV-01": 23, "AGV-02": 14}))

    def test_static_obstacle_distance_can_reverse_manhattan_ranking(self):
        grid = GridMap("detour", ("#########", "#P#U...P#", "#.#....D#", "#.......#", "#########"))
        scenario = Scenario("detour", grid, (VehicleSpec("A", (1, 1)), VehicleSpec("B", (7, 1))),
                            (TaskSpec("T", 0, (3, 1), (7, 2)),), dispatch_policy="B0")
        result = run(scenario)
        self.assertEqual(json.loads(result.dispatches[0]["idle_distances"]), {"A": 6, "B": 4})
        self.assertEqual(result.dispatches[0]["vehicle_id"], "B")
        self.assertTrue(verify(result)["dispatch_ok"])

    def test_equal_distance_and_release_ties_use_ids(self):
        scenario = automatic("two_shared_pickup.json")
        result = run(replace(scenario, vehicles=scenario.vehicles[::-1], tasks=scenario.tasks[::-1]))
        self.assertEqual(json.loads(result.dispatches[0]["idle_distances"]), {"AGV-01": 3, "AGV-02": 3})
        self.assertEqual([(d["task_id"], d["vehicle_id"]) for d in result.dispatches],
                         [("T001", "AGV-01"), ("T002", "AGV-02")])

    def test_next_job_releases_previous_terminal_reservation(self):
        scenario = automatic("two_same_delivery_blocked.json")
        source = automatic("two_shared_pickup.json")
        followup = replace(source.tasks[1], id="T003")
        result = run(replace(source, tasks=scenario.tasks + (followup,), max_steps=50))
        self.assertTrue(result.summary["success"])
        self.assertGreater(result.summary["planning_failures"], 0)
        self.assertEqual(result.summary["conflict_count"], 0)
        self.assertTrue(verify(result)["dispatch_ok"])
        self.assertEqual(result.dispatches[2]["vehicle_id"], result.dispatches[0]["vehicle_id"])
        self.assertEqual(result.dispatches[2]["time"], result.task_rows[0]["completed_at"])

    def test_timeout_preserves_unreleased_queued_and_assigned_tasks(self):
        scenario = load_scenario(ROOT / "instances/b0_wide_8.json")
        result = run(replace(scenario, max_steps=1))
        self.assertEqual(len(result.dispatches), 2)
        self.assertEqual(len(result.task_rows), 8)
        self.assertEqual({r["status"] for r in result.task_rows}, {"pending", "assigned", "unreleased"})
        self.assertFalse(result.summary["success"])
        self.assertIsNone(result.summary["mean_flow_time"])
        self.assertTrue(verify(result)["dispatch_ok"])

    def test_empty_dispatch_file_has_header_and_no_invented_assignments(self):
        scenario = automatic("two_shared_pickup.json")
        result = run(replace(scenario, tasks=tuple(replace(t, release_time=8) for t in scenario.tasks), max_steps=4))
        with TemporaryDirectory() as temp:
            directory = Path(temp) / "run"
            save_result(result, directory)
            self.assertIn("idle_distances", (directory / "dispatch.csv").read_text(encoding="utf-8-sig"))
            self.assertEqual(read_csv(directory / "dispatch.csv"), [])
            self.assertEqual(load_scenario(directory / "instance.json").dispatch_policy, "B0")
        self.assertEqual(verify(result)["checked_dispatches"], 0)

    def test_replay_rejects_falsified_dispatch_evidence(self):
        result = run(automatic("two_shared_pickup.json"))
        for field, value in (("task_id", "T002"), ("vehicle_id", "AGV-02"), ("time", 1),
                             ("idle_distances", "{}"), ("pickup_distance", 99)):
            altered = [dict(row) for row in result.dispatches]
            altered[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Dispatch 1"):
                verify(result, altered)
