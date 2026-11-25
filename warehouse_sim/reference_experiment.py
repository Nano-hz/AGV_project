"""E5 小规模枚举。每种领取顺序和车辆分配都通过正式仿真入口执行。"""

from dataclasses import replace
from itertools import permutations, product
import json

from .experiment_inputs import Case, PICKUPS, make_input, read_grids
from .experiments import verify_dispatch_run
from .models import AUTO_POLICIES
from .output import read_csv, save_result
from .simulation.simulator import run
from .supplementary import policy_runs, prepare, table


# 手工实例用正式地图上的取货位、送达位索引（均从 0 开始），故意包含重复取货和同站送货。
HAND_CASES = {
    "hand_shared_pickup": ("wide", ((0, 0), (0, 3), (3, 2))),
    "hand_shared_delivery": ("bottleneck", ((0, 0), (3, 0), (1, 1), (2, 2))),
}
RANDOM_CASES = (Case("narrow", 2, 3, 0), Case("bottleneck", 2, 4, 1))


def reference_inputs(grids):
    for name, (layout, pairs) in HAND_CASES.items():
        grid = grids[layout]
        base = make_input(Case(layout, 2, len(pairs), 0), grid)
        tasks = tuple(replace(task, pickup=PICKUPS[layout][p], delivery=grid.cells("D")[d])
                      for task, (p, d) in zip(base.tasks, pairs))
        yield replace(base, name=name, tasks=tasks)
    for case in RANDOM_CASES:
        yield replace(make_input(case, grids[case.layout]), name=f"random_{case.id}")


def ordered_scenarios(common):
    """产生 n! × 2^n 个互异的全序列，包含同一辆车承接全部订单的分配。"""
    if len(common.vehicles) != 2 or len(common.tasks) not in (3, 4):
        raise ValueError("E5 requires two vehicles and three or four tasks")
    vehicles = sorted(v.id for v in common.vehicles)
    for order in permutations(sorted(task.id for task in common.tasks)):
        for owners in product(vehicles, repeat=len(order)):
            yield replace(common, dispatch_policy="ordered", dispatch_order=tuple(zip(order, owners)))


def candidate_record(number, scenario, summary):
    return {
        "schedule_id": number,
        "dispatch_order": json.dumps(scenario.dispatch_order, separators=(",", ":")),
        **{k: summary[k] for k in ("success", "completed_tasks", "mean_flow_time", "makespan", "simulation_steps",
                                   "vertex_conflicts", "edge_swap_conflicts", "failure_reason")},
    }


def enumerate_case(root, common, verify):
    """逐个模拟序列。仅完整、安全的运行参与最小值比较，保存获选序列的完整轨迹。"""
    candidates = []
    best = best_key = None
    for number, scenario in enumerate(ordered_scenarios(common), 1):
        result = run(scenario)
        row = candidate_record(number, scenario, result.summary)
        candidates.append(row)
        if row["success"]:
            key = (row["mean_flow_time"], row["makespan"], number)
            if best_key is None or key < best_key:
                best_key, best = key, result
    if best is None:
        raise ValueError(f"{common.name}: no enumerated schedule completed safely")
    directory = root / "reference" / common.name
    if verify:
        summary = verify_dispatch_run(directory, best.scenario)
        if candidate_record(best_key[2], best.scenario, summary) != candidates[best_key[2] - 1]:
            raise ValueError(f"{directory}: saved reference differs from the enumeration minimum")
    else:
        save_result(best, directory)
    table(directory / "candidates.csv", candidates, verify)
    feasible = [row for row in candidates if row["success"]]
    return {
        "case_id": common.name, "task_count": len(common.tasks), "schedules": len(candidates),
        "complete_schedules": len(feasible), "best_schedule_id": best_key[2],
        "reference_mean_flow_time": best_key[0], "makespan_at_best_flow": best_key[1],
        "min_makespan": min(r["makespan"] for r in feasible),
    }, candidates


def reference_experiment(directory, maps_dir, verify=False):
    grids = read_grids(maps_dir)
    inputs = list(reference_inputs(grids))
    root = prepare(directory, {
        "experiment": "E5", "cases": [s.name for s in inputs], "policies": list(AUTO_POLICIES),
        "objective": ["mean_flow_time", "makespan", "schedule_id"],
        "enumeration": "Every task permutation and vehicle assignment. In order, reserve each pair at its first feasible tick.",
    }, verify)
    runs, references, gaps = [], [], []
    for common in inputs:
        rows = policy_runs(root, common, verify)
        reference, candidates = enumerate_case(root, common, verify)
        # 将 P 的实际派单序列放回枚举表，两条独立执行途径必须得到同样的完成指标。
        aware = next(row for row in rows if row["method"] == "P")
        if aware["success"]:
            decisions = read_csv(root / aware["run_dir"] / "dispatch.csv")
            order = [[d["task_id"], d["vehicle_id"]] for d in decisions]
            match = next(row for row in candidates if json.loads(row["dispatch_order"]) == order)
            if (match["mean_flow_time"], match["makespan"]) != (aware["mean_flow_time"], aware["makespan"]):
                raise ValueError(f"{common.name}: enumerating P's dispatch order did not reproduce P")
        for row in rows:
            score, optimum = row["mean_flow_time"], reference["reference_mean_flow_time"]
            gaps.append({
                "case_id": common.name, "method": row["method"], "completed_tasks": row["completed_tasks"],
                "task_count": row["task_count"], "timeout": row["timeout"], "mean_flow_time": score,
                "reference_mean_flow_time": optimum,
                "gap_pct": round(100 * (score - optimum) / optimum, 6) if row["success"] else None,
                "makespan": row["makespan"], "vertex_conflicts": row["vertex_conflicts"],
                "edge_swap_conflicts": row["edge_swap_conflicts"],
            })
        runs.extend(rows)
        references.append(reference)
        print(f"{common.name}: {len(candidates)} schedules, best mean flow {reference['reference_mean_flow_time']:.3f}", flush=True)
    table(root / "runs.csv", runs, verify)
    table(root / "references.csv", references, verify)
    table(root / "comparison.csv", gaps, verify)
    return {"inputs": len(inputs), "policy_runs": len(runs), "schedules": sum(r["schedules"] for r in references),
            "reference_runs_saved": len(references)}
