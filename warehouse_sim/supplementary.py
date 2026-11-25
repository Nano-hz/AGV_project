"""E4 分批发布对照，以及补充实验共用的数据保存与复核。"""

from dataclasses import replace
from pathlib import Path

from .experiment_inputs import Case, SEEDS, make_input, read_grids
from .experiment_report import _paired, _summarize
from .experiments import OUTCOME_FIELDS, csv_rows, verify_dispatch_run
from .models import AUTO_POLICIES, load_scenario, read_json
from .output import read_csv, save_result, write_csv, write_json
from .simulation.simulator import run


def prepare(directory, manifest, verify):
    directory = Path(directory)
    if verify:
        if read_json(directory / "manifest.json") != manifest:
            raise ValueError("Experiment manifest differs from the specified design")
    else:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "instances").mkdir()
        write_json(directory / "manifest.json", manifest)
    return directory


def table(path, rows, verify):
    if verify:
        if read_csv(path) != csv_rows(rows):
            raise ValueError(f"{path}: table differs from the recomputed results")
    else:
        write_csv(path, rows)


def policy_runs(root, common, verify):
    """逐个策略复用同一份实例，复核时逐帧重算派单和完成时刻。"""
    instance = root / "instances" / f"{common.name}.json"
    if verify:
        if load_scenario(instance) != common:
            raise ValueError(f"{instance}: saved input differs from the experiment design")
    else:
        write_json(instance, common.as_dict())
    rows = []
    for policy in AUTO_POLICIES:
        directory = root / "runs" / common.name / policy
        scenario = replace(common, dispatch_policy=policy)
        if verify:
            summary = verify_dispatch_run(directory, scenario)
        else:
            result = run(scenario)
            save_result(result, directory)
            summary = result.summary
        rows.append({
            "case_id": common.name, "seed": common.seed, "method": policy,
            "task_count": len(common.tasks),
            **{field: summary[field] for field in OUTCOME_FIELDS},
            "timeout": summary["completed_tasks"] < len(common.tasks) and summary["simulation_steps"] == common.max_steps,
            "run_dir": directory.relative_to(root).as_posix(),
        })
    return rows


RELEASES = {"simultaneous": (0, 0, 0, 0), "waves": (0, 10, 20, 30)}


def release_inputs(grid, seed):
    """固定同一批订单，按编号将每四件货放入一个发布批次。"""
    base = make_input(Case("bottleneck", 2, 16, seed), grid)
    for mode, times in RELEASES.items():
        tasks = tuple(replace(task, release_time=times[index // 4]) for index, task in enumerate(base.tasks))
        yield mode, replace(base, name=f"{base.name}_{mode}", tasks=tasks)


def release_experiment(directory, maps_dir, verify=False):
    manifest = {
        "experiment": "E4", "layout": "bottleneck", "vehicles": 2, "tasks": 16, "seeds": list(SEEDS),
        "policies": list(AUTO_POLICIES), "batch_size": 4,
        "release_ticks": {mode: list(times) for mode, times in RELEASES.items()},
    }
    root = prepare(directory, manifest, verify)
    grid = read_grids(maps_dir)["bottleneck"]
    rows = []
    for seed in SEEDS:
        for mode, common in release_inputs(grid, seed):
            rows.extend({"release_mode": mode, **row} for row in policy_runs(root, common, verify))
    groups = {(mode, policy): [r for r in rows if r["release_mode"] == mode and r["method"] == policy]
              for mode in RELEASES for policy in AUTO_POLICIES}
    table(root / "runs.csv", rows, verify)
    table(root / "summary.csv", [
        {"release_mode": mode, "method": policy, **_summarize(group)} for (mode, policy), group in groups.items()
    ], verify)
    table(root / "paired_release.csv", [
        {"method": policy, **_paired(groups["waves", policy], groups["simultaneous", policy])}
        for policy in AUTO_POLICIES
    ], verify)
    table(root / "paired_policy.csv", [
        {"release_mode": mode, "baseline": baseline, **_paired(groups[mode, "P"], groups[mode, baseline])}
        for mode in RELEASES for baseline in ("B0", "B1")
    ], verify)
    return {"inputs": len(SEEDS) * 2, "policy_runs": len(rows)}
