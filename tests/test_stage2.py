"""Two-vehicle checks using hand-sized cases with known conflicts or detours."""

from dataclasses import replace
from pathlib import Path
import unittest

from warehouse_sim.collisions import audit_trajectory
from warehouse_sim.models import Scenario, load_scenario
from warehouse_sim.simulator import run
from warehouse_sim.space_time import Reservation, can_step


INSTANCES = Path(__file__).resolve().parents[1] / "instances"


def instance(name):
    return load_scenario(INSTANCES / f"two_{name}.json")


def at(result, vehicle, tick):
    return next(row for row in result.trace if row["vehicle_id"] == vehicle and row["time"] == tick)


class AvoidanceTests(unittest.TestCase):
    def assert_both_delivered(self, result):
        self.assertTrue(result.summary["success"])
        self.assertEqual(result.summary["completed_tasks"], 2)
        self.assertEqual(result.summary["conflict_count"], 0)
        self.assertEqual(len(result.trace), 2 * (result.summary["simulation_steps"] + 1))
        for task in result.task_rows:
            self.assertLess(task["pickup_started_at"], task["picked_at"])
            self.assertLess(task["picked_at"], task["completed_at"])

    def test_crossing_reserves_vertex(self):
        result = run(instance("crossing"))
        self.assert_both_delivered(result)
        self.assertEqual((at(result, "AGV-01", 2)["x"], at(result, "AGV-01", 2)["y"]), (3, 3))
        self.assertEqual(at(result, "AGV-02", 2)["action"], "wait")
        self.assertEqual((at(result, "AGV-02", 3)["x"], at(result, "AGV-02", 3)["y"]), (3, 3))

    def test_reverse_edge_is_blocked_even_when_destination_is_free_at_next_tick(self):
        other = Reservation(5, ((2, 1), (1, 1)))
        self.assertNotEqual(other.at(6), (2, 1))
        self.assertFalse(can_step((other,), (1, 1), (2, 1), 5))
        self.assertTrue(can_step((other,), (1, 1), (1, 2), 5))

    def test_head_on_aisle_uses_passing_bay(self):
        result = run(instance("passing_bay"))
        self.assert_both_delivered(result)
        side = at(result, "AGV-02", 8)
        straight = at(result, "AGV-01", 8)
        self.assertEqual((side["x"], side["y"]), (6, 1))
        self.assertEqual((straight["x"], straight["y"]), (6, 2))

    def test_two_distinct_tasks_use_same_pickup_at_different_times(self):
        result = run(instance("shared_pickup"))
        self.assert_both_delivered(result)
        first, second = result.task_rows
        self.assertEqual((first["pickup_x"], first["pickup_y"]), (4, 2))
        self.assertEqual((second["pickup_x"], second["pickup_y"]), (4, 2))
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertEqual((first["pickup_started_at"], first["picked_at"]), (3, 4))
        self.assertEqual((second["pickup_started_at"], second["picked_at"]), (5, 6))

    def test_multiple_service_ticks_keep_pickup_reserved(self):
        result = run(replace(instance("shared_pickup"), pickup_steps=3, dropoff_steps=2))
        self.assert_both_delivered(result)
        for task in result.task_rows:
            for tick in range(task["pickup_started_at"] + 1, task["picked_at"] + 1):
                row = at(result, task["vehicle_id"], tick)
                self.assertEqual((row["x"], row["y"], row["action"]), (4, 2, "pickup"))
            self.assertEqual(task["picked_at"] - task["pickup_started_at"], 3)
            self.assertEqual(task["completed_at"] - task["dropoff_started_at"], 2)
        self.assertLess(result.task_rows[0]["picked_at"], result.task_rows[1]["pickup_started_at"])

    def test_plan_is_retried_when_second_vehicle_leaves_its_start(self):
        result = run(instance("retry"))
        self.assert_both_delivered(result)
        events = [(row["time"], row["event"], row["reason"]) for row in result.events if row["vehicle_id"] == "AGV-01"]
        self.assertIn((0, "plan_unavailable", "stationary_vehicle_blocks_route"), events)
        self.assertIn((1, "plan_committed", ""), events)
        self.assertEqual(at(result, "AGV-01", 1)["action"], "wait")

    def test_idle_vehicle_keeps_delivery_reserved_and_blocks_second_task(self):
        result = run(instance("same_delivery_blocked"))
        self.assertFalse(result.summary["success"])
        self.assertEqual(result.summary["failure_reason"], "max_steps_exceeded")
        self.assertEqual(result.summary["completed_tasks"], 1)
        self.assertEqual(result.summary["conflict_count"], 0)
        self.assertIsNone(result.summary["mean_flow_time"])
        self.assertIn("delivery_reserved_for_stop", {row["reason"] for row in result.events})
        for tick in range(6, result.summary["simulation_steps"] + 1):
            row = at(result, "AGV-01", tick)
            self.assertEqual((row["x"], row["y"], row["phase"]), (4, 1, "idle"))

    def test_round_trip_keeps_fixed_assignments_and_sort_order(self):
        scenario = instance("shared_pickup")
        reversed_input = replace(scenario, vehicles=scenario.vehicles[::-1], tasks=scenario.tasks[::-1])
        restored = Scenario.from_dict(reversed_input.as_dict())
        self.assertEqual(run(scenario).trace, run(restored).trace)
        missing = replace(scenario.tasks[0], vehicle_id=None)
        with self.assertRaisesRegex(ValueError, "one fixed task per vehicle"):
            run(replace(scenario, tasks=(missing, scenario.tasks[1])))


class AuditTests(unittest.TestCase):
    def test_audit_detects_tampered_vertex_collision(self):
        scenario = instance("crossing")
        rows = [row.copy() for row in run(scenario).trace if row["time"] <= 2]
        next(row for row in rows if row["time"] == 2 and row["vehicle_id"] == "AGV-02")["y"] = 3
        result = audit_trajectory(scenario, rows, 2)
        self.assertEqual(result["vertex_conflicts"], 1)
        self.assertEqual(result["edge_swap_conflicts"], 0)
        self.assertEqual(result["first_conflict"]["time"], 2)

    def test_audit_detects_swap_with_two_distinct_cells_in_every_frame(self):
        scenario = instance("retry")
        rows = [
            {"time": tick, "vehicle_id": vehicle.id, "x": x, "y": 1}
            for tick, pair in enumerate(((1, 3), (2, 3), (3, 2)))
            for vehicle, x in zip(scenario.vehicles, pair)
        ]
        result = audit_trajectory(scenario, rows, 2)
        self.assertEqual(result["vertex_conflicts"], 0)
        self.assertEqual(result["edge_swap_conflicts"], 1)
        self.assertEqual(result["first_conflict"]["type"], "edge_swap")

    def test_audit_rejects_missing_vehicle_frame(self):
        scenario = instance("crossing")
        result = run(scenario)
        with self.assertRaisesRegex(ValueError, "Missing vehicle position"):
            audit_trajectory(scenario, result.trace[:-1], result.summary["simulation_steps"])
