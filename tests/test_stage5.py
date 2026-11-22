"""Exercise shared inputs, four-vehicle verification, and timing with timeouts."""

from dataclasses import replace
from pathlib import Path
import unittest

from warehouse_sim.experiment_inputs import Case, PICKUPS, make_input, read_grids
from warehouse_sim.experiment_report import _paired, _summarize
from warehouse_sim.simulation.collisions import audit_trajectory
from warehouse_sim.simulation.dispatch_audit import audit_dispatch
from warehouse_sim.simulation.simulator import run


MAPS = Path(__file__).resolve().parents[1] / "maps"


class MainExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grids = read_grids(MAPS)

    def test_seed_count_and_fleet_derive_from_one_task_sequence(self):
        for layout, grid in self.grids.items():
            with self.subTest(layout=layout):
                large = make_input(Case(layout, 4, 24, 6), grid)
                small = make_input(Case(layout, 2, 8, 6), grid)
                self.assertEqual(small.tasks, large.tasks[:8])
                self.assertEqual(small.vehicles, large.vehicles[::3])
                self.assertEqual({task.release_time for task in large.tasks}, {0})
                self.assertLessEqual({task.pickup for task in large.tasks}, set(PICKUPS[layout]))
                self.assertEqual(large.max_steps, 1000)

    def test_four_vehicle_p_reserves_and_replays_every_vehicle(self):
        common = make_input(Case("wide", 4, 8, 0), self.grids["wide"])
        scenario = replace(common, dispatch_policy="P")
        result = run(scenario)
        self.assertEqual(result.summary["vehicle_count"], 4)
        self.assertEqual(result.summary["conflict_check_scope"], "all_vehicle_pairs")
        self.assertEqual({row["vehicle_id"] for row in result.trace}, {v.id for v in scenario.vehicles})
        end = result.summary["simulation_steps"]
        self.assertEqual(audit_trajectory(scenario, result.trace, end)["conflict_count"], 0)
        self.assertEqual(audit_dispatch(scenario, result.trace, result.dispatches, result.task_rows, end)
                         ["recomputed_completed_tasks"], 8)

    def test_timeout_contributes_to_rates_and_paired_time_uses_shared_success_seeds(self):
        complete = {"seed": 0, "success": True, "timeout": False, "task_count": 8, "completed_tasks": 8,
                    "mean_flow_time": 100, "makespan": 150, "completion_rate": 1.0,
                    "conflict_count": 0, "vertex_conflicts": 0, "edge_swap_conflicts": 0}
        timeout = {**complete, "seed": 1, "success": False, "timeout": True, "completed_tasks": 4,
                   "mean_flow_time": None, "makespan": None, "completion_rate": 0.5}
        baseline = [complete, timeout]
        proposed = [{**complete, "mean_flow_time": 90, "makespan": 165}, {**complete, "seed": 1}]
        totals = _summarize(baseline)
        self.assertEqual((totals["complete_runs"], totals["timeout_runs"], totals["task_completion_rate"]), (1, 1, 0.75))
        self.assertEqual(totals["mean_flow_time"], 100)
        self.assertIsNone(totals["sd_flow_time"])
        paired = _paired(proposed, baseline)
        self.assertEqual((paired["paired_complete_runs"], paired["paired_complete_seeds"]), (1, "0"))
        self.assertEqual((paired["flow_improvement_pct"], paired["makespan_improvement_pct"]), (10, -10))
        self.assertEqual(paired["task_completion_gain_pp"], 25)
