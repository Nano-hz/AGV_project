"""Check policy scores, reservation effects, and comparison evidence."""

from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warehouse_sim.__main__ import main
from warehouse_sim.models import AUTO_POLICIES, load_scenario
from warehouse_sim.output import read_csv, write_json
from warehouse_sim.simulation.dispatch_audit import audit_dispatch
from warehouse_sim.simulation.simulator import run


INSTANCES = Path(__file__).resolve().parents[1] / "instances"


def shared_pickup():
    fixed = load_scenario(INSTANCES / "two_shared_pickup.json")
    return replace(fixed, tasks=tuple(replace(task, vehicle_id=None) for task in fixed.tasks))


def verify_dispatch(result, decisions=None):
    return audit_dispatch(result.scenario, result.trace, result.dispatches if decisions is None else decisions,
                          result.task_rows, result.summary["simulation_steps"])


class CompletionDispatchTests(unittest.TestCase):
    def test_b1_compares_all_ready_pairs_and_resolves_equal_finish_by_task_id(self):
        result = run(replace(load_scenario(INSTANCES / "b0_wide_8.json"), dispatch_policy="B1"))
        first = result.dispatches[0]
        self.assertEqual((first["task_id"], first["vehicle_id"], first["estimated_finish"]), ("T004", "AGV-01", 25))
        scores = {(c["task_id"], c["vehicle_id"]): c["estimated_finish"] for c in json.loads(first["candidates"])}
        self.assertEqual(len(scores), 8)
        self.assertEqual(scores["T005", "AGV-02"], 25)
        self.assertEqual(scores["T002", "AGV-02"], 34)
        self.assertNotIn(("T001", "AGV-01"), scores)
        self.assertTrue(verify_dispatch(result)["dispatch_ok"])

    def test_p_accounts_for_shared_pickup_reservation_and_uses_selected_route(self):
        scenario = shared_pickup()
        b1 = run(replace(scenario, dispatch_policy="B1"))
        aware = run(replace(scenario, dispatch_policy="P"))
        self.assertEqual(b1.dispatches[1]["estimated_finish"], 6)
        self.assertEqual(aware.dispatches[1]["estimated_finish"], 8)
        score = json.loads(aware.dispatches[1]["candidates"])[0]
        self.assertEqual((score["static_finish"], score["estimated_finish"]), (6, 8))
        self.assertEqual(aware.task_rows[1]["completed_at"], 8)
        self.assertEqual(aware.summary["vertex_conflicts"] + aware.summary["edge_swap_conflicts"], 0)
        self.assertTrue(verify_dispatch(aware)["dispatch_ok"])

    def test_p_skips_unavailable_candidate_instead_of_assigning_it(self):
        wide = load_scenario(INSTANCES / "b0_wide_8.json")
        result = run(replace(wide, dispatch_policy="P"))
        decision = next(row for row in result.dispatches if row["time"] == 57)
        self.assertEqual(decision["task_id"], "T002")
        blocked = next(candidate for candidate in json.loads(decision["candidates"]) if candidate["task_id"] == "T003")
        self.assertIsNone(blocked["estimated_finish"])
        self.assertEqual(blocked["unavailable_reason"], "delivery_reserved_for_stop")
        altered = [row.copy() for row in result.dispatches]
        altered[0]["estimated_finish"] += 1
        with self.assertRaisesRegex(ValueError, "candidate completion estimates"):
            verify_dispatch(result, altered)

    def test_p_preserves_pending_tasks_when_no_plan_fits_deadline(self):
        result = run(replace(shared_pickup(), dispatch_policy="P", max_steps=1))
        self.assertEqual(result.dispatches, [])
        self.assertEqual([row["status"] for row in result.task_rows], ["pending", "pending"])
        self.assertEqual(verify_dispatch(result)["recomputed_completed_tasks"], 0)
        self.assertTrue(any(event["event"] == "dispatch_deferred" for event in result.events))


class ComparisonTests(unittest.TestCase):
    def test_compare_keeps_inputs_and_verifier_detects_modified_finish_metrics(self):
        with TemporaryDirectory() as temp, redirect_stdout(StringIO()) as printed:
            root = Path(temp) / "comparison"
            self.assertEqual(main(["compare", "--instance", str(INSTANCES / "b0_wide_8.json"), "--output", str(root)]), 0)
            self.assertEqual([row["method"] for row in read_csv(root / "comparison.csv")], list(AUTO_POLICIES))
            inputs = [load_scenario(root / policy / "instance.json") for policy in AUTO_POLICIES]
            for policy, input_scenario in zip(AUTO_POLICIES, inputs):
                self.assertEqual(input_scenario, replace(inputs[0], dispatch_policy=policy))
                self.assertEqual(main(["verify", str(root / policy)]), 0)
            summary_file = root / "P" / "summary.json"
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
            summary["makespan"] -= 1
            write_json(summary_file, summary)
            self.assertEqual(main(["verify", str(root / "P")]), 2)
            self.assertIn('"completion_time_ok": false', printed.getvalue())
