"""Run and verify the main comparison with one saved input per seed and setting."""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from .experiment_inputs import MAX_STEPS, PICKUPS, SEEDS, TASK_COUNTS, VEHICLE_COUNTS, cases, make_input, read_grids
from .models import AUTO_POLICIES, load_scenario, read_json
from .output import read_csv, save_result, write_csv, write_json
from .simulation.collisions import audit_trajectory
from .simulation.dispatch_audit import audit_dispatch
from .simulation.simulator import run


OUTCOME_FIELDS = (
    "success", "completed_tasks", "completion_rate", "mean_flow_time", "makespan",
    "simulation_steps", "vertex_conflicts", "edge_swap_conflicts", "conflict_count",
    "failure_reason", "planning_failures", "runtime_seconds", "total_distance", "total_wait_steps",
)


def _record(case, summary, events, max_steps):
    last_tick = summary["simulation_steps"]
    timeout = last_tick == max_steps and summary["completed_tasks"] < case.task_count
    final_reasons = Counter(
        row["reason"] for row in events
        if row.get("reason") and int(row["time"]) == last_tick - 1
    ) if timeout else Counter()
    method = summary["method"]
    return {
        "case_id": case.id, "layout": case.layout, "vehicle_count": case.vehicle_count,
        "task_count": case.task_count, "seed": case.seed, "method": method,
        **{field: summary[field] for field in OUTCOME_FIELDS},
        "timeout": timeout, "final_blocking_reasons": json.dumps(final_reasons, sort_keys=True),
        "run_dir": f"runs/{case.id}/{method}",
    }


def _run_case(root, case, common):
    records = []
    for policy in AUTO_POLICIES:
        result = run(replace(common, dispatch_policy=policy))
        save_result(result, root / "runs" / case.id / policy)
        records.append(_record(case, result.summary, result.events, common.max_steps))
    return records


def _grid_hash(grid):
    return sha256(json.dumps(grid.as_dict(), sort_keys=True).encode("utf-8")).hexdigest()


def _collect(worker, jobs, workers, verb):
    results = {}
    total = len(jobs)
    if workers == 1:
        iterator = ((case_id, worker(*args)) for case_id, args in jobs)
        for index, (case_id, rows) in enumerate(iterator, 1):
            results[case_id] = rows
            if index == total or index % 15 == 0:
                print(f"{verb}: {index}/{total} matched inputs ({index * 3} runs)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(worker, *args): case_id for case_id, args in jobs}
            for index, future in enumerate(as_completed(futures), 1):
                case_id = futures[future]
                try:
                    results[case_id] = future.result()
                except Exception as exc:
                    raise RuntimeError(f"{case_id}: {exc}") from exc
                if index == total or index % 15 == 0:
                    print(f"{verb}: {index}/{total} matched inputs ({index * 3} runs)", flush=True)
    return [row for case_id, _ in jobs for row in results[case_id]]


def run_experiment(root, maps_dir, seeds=SEEDS, workers=1):
    root = Path(root).resolve()
    seeds = tuple(sorted(seeds))
    if not seeds or len(set(seeds)) != len(seeds) or min(seeds) < 0 or workers < 1:
        raise ValueError("Use unique nonnegative seeds and at least one worker")
    grids = read_grids(maps_dir)
    root.mkdir(parents=True, exist_ok=False)
    (root / "instances").mkdir()
    write_json(root / "manifest.json", {
        "schema_version": 1, "layouts": list(PICKUPS), "vehicle_counts": VEHICLE_COUNTS,
        "task_counts": TASK_COUNTS, "seeds": seeds, "policies": AUTO_POLICIES, "max_steps": MAX_STEPS,
        "pickup_steps": 1, "dropoff_steps": 1, "release_time": 0,
        "map_sha256": {name: _grid_hash(grid) for name, grid in grids.items()},
        "pickup_positions": PICKUPS,
        "sampling": "Seeded uniform pickup/delivery indexes with replacement. Loads use prefixes. "
                    "Two vehicles use the first and last of the four fixed parking cells.",
    })
    jobs = []
    for case in cases(seeds):
        common = make_input(case, grids[case.layout])
        write_json(root / "instances" / f"{case.id}.json", common.as_dict())
        jobs.append((case.id, (root, case, common)))
    rows = _collect(_run_case, jobs, workers, "Simulated")
    write_csv(root / "runs.csv", rows)
    return rows


def csv_rows(rows):
    return [{key: "" if value is None else str(value) for key, value in row.items()} for row in rows]


def _verify_case(root, case, manifest):
    common = load_scenario(root / "instances" / f"{case.id}.json")
    if common != make_input(case, common.grid, manifest["max_steps"]):
        raise ValueError(f"{case.id}: saved input differs from its seed and configuration")
    if _grid_hash(common.grid) != manifest["map_sha256"][case.layout]:
        raise ValueError(f"{case.id}: map differs from the experiment manifest")

    records = []
    for policy in AUTO_POLICIES:
        directory = root / "runs" / case.id / policy
        instance = directory / "instance.json"
        scenario = load_scenario(instance)
        if scenario != replace(common, dispatch_policy=policy):
            raise ValueError(f"{case.id}/{policy}: the policy used different inputs")
        if sha256(instance.read_bytes()).hexdigest() != read_json(directory / "metadata.json")["instance_sha256"]:
            raise ValueError(f"{case.id}/{policy}: snapshot hash differs from metadata")
        summary = read_json(directory / "summary.json")
        trace = read_csv(directory / "trajectory.csv")
        audit = audit_trajectory(scenario, trace, summary["simulation_steps"])
        dispatch = audit_dispatch(scenario, trace, read_csv(directory / "dispatch.csv"),
                                  read_csv(directory / "tasks.csv"), summary["simulation_steps"])
        for field in ("completed_tasks", "makespan", "mean_flow_time"):
            if summary[field] != dispatch[f"recomputed_{field}"]:
                raise ValueError(f"{case.id}/{policy}: {field} disagrees with the saved trajectory")
        for field in ("vertex_conflicts", "edge_swap_conflicts", "conflict_count"):
            if summary[field] != audit[field]:
                raise ValueError(f"{case.id}/{policy}: {field} disagrees with the saved trajectory")
        expected_success = summary["completed_tasks"] == case.task_count and audit["conflict_count"] == 0
        if (summary["success"] != expected_success or summary["task_count"] != case.task_count
                or summary["vehicle_count"] != case.vehicle_count or summary["method"] != policy
                or summary["completion_rate"] != summary["completed_tasks"] / case.task_count):
            raise ValueError(f"{case.id}/{policy}: summary counts or status do not match the run")
        records.append(_record(case, summary, read_csv(directory / "events.csv"), common.max_steps))
    return records


def verify_experiment(root, workers=1):
    root = Path(root).resolve()
    manifest = read_json(root / "manifest.json")
    if (manifest["schema_version"] != 1 or manifest["policies"] != list(AUTO_POLICIES)
            or manifest["layouts"] != list(PICKUPS) or manifest["max_steps"] != MAX_STEPS
            or manifest["vehicle_counts"] != list(VEHICLE_COUNTS) or manifest["task_counts"] != list(TASK_COUNTS)
            or len(set(manifest["seeds"])) != len(manifest["seeds"]) or not manifest["seeds"]
            or workers < 1):
        raise ValueError("Unsupported or inconsistent experiment manifest")
    jobs = [(case.id, (root, case, manifest)) for case in cases(manifest["seeds"])]
    records = _collect(_verify_case, jobs, workers, "Verified")
    if read_csv(root / "runs.csv") != csv_rows(records):
        raise ValueError("runs.csv disagrees with the verified run records")
    return len(jobs), len(records)
