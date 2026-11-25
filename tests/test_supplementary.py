"""覆盖配对发布、完整枚举以及参考序列的独立回放。"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warehouse_sim.experiment_inputs import read_grids
from warehouse_sim.models import GridMap, Scenario, TaskSpec, VehicleSpec, load_scenario
from warehouse_sim.output import read_csv, write_csv
from warehouse_sim.reference_experiment import enumerate_case, ordered_scenarios
from warehouse_sim.supplementary import release_inputs


class SupplementaryTests(unittest.TestCase):
    def setUp(self):
        self.small = Scenario(
            "two_lanes", GridMap("two_lanes", ("PUD", "...", "PUD")),
            (VehicleSpec("A", (0, 0)), VehicleSpec("B", (0, 2))),
            (TaskSpec("1", 0, (1, 0), (2, 0)), TaskSpec("2", 0, (1, 0), (2, 0)),
             TaskSpec("3", 0, (1, 2), (2, 2))), max_steps=20, dispatch_policy="B0",
        )

    def test_paired_releases_only_change_times(self):
        grid = read_grids(Path(__file__).resolve().parents[1] / "maps")["bottleneck"]
        modes = dict(release_inputs(grid, 7))
        baseline, waves = modes["simultaneous"], modes["waves"]
        self.assertEqual([t.release_time for t in waves.tasks], [0]*4 + [10]*4 + [20]*4 + [30]*4)
        normalized = tuple(replace(t, release_time=0) for t in waves.tasks)
        self.assertEqual(replace(waves, name=baseline.name, tasks=normalized), baseline)

    def test_enumeration_contains_every_order_and_owner(self):
        inputs = list(ordered_scenarios(self.small))
        self.assertEqual(len(inputs), 48)
        self.assertEqual(len({s.dispatch_order for s in inputs}), 48)
        self.assertIn((("2", "B"), ("1", "B"), ("3", "B")), [s.dispatch_order for s in inputs])
        invalid = replace(inputs[0], dispatch_order=(("1", "A"), ("1", "B"), ("3", "A")))
        with self.assertRaises(ValueError):
            invalid.validate()

    def test_reference_reaches_hand_bound_and_verifier_detects_tampering(self):
        # 首单至少 4 步，至少一车要做两单且第二单至少到第 8 步才能完成。
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            best, _ = enumerate_case(root, self.small, False)
            self.assertEqual((best["reference_mean_flow_time"], best["makespan_at_best_flow"]), (16 / 3, 8))
            self.assertEqual(enumerate_case(root, self.small, True)[0], best)
            folder = root / "reference" / self.small.name
            self.assertEqual(load_scenario(folder / "instance.json").dispatch_policy, "ordered")
            ledger = folder / "candidates.csv"
            rows = read_csv(ledger)
            rows.pop()
            write_csv(ledger, rows)
            with self.assertRaisesRegex(ValueError, "candidates.csv"):
                enumerate_case(root, self.small, True)
