"""CLI for running, validating, and inspecting warehouse simulations."""

import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sys

from .models import AUTO_POLICIES, load_scenario, read_json
from .output import read_csv, save_result, write_csv
from .simulation.collisions import audit_trajectory
from .simulation.dispatch_audit import audit_dispatch
from .simulation.simulator import run

ROOT = Path(__file__).resolve().parents[1]


def _compare(scenario, directory):
    if scenario.dispatch_policy not in AUTO_POLICIES:
        raise ValueError("Comparison requires an automatic-dispatch instance")
    directory.mkdir(parents=True, exist_ok=False)
    columns = (
        "method", "success", "task_count", "completed_tasks", "completion_rate",
        "mean_flow_time", "makespan", "vertex_conflicts", "edge_swap_conflicts", "failure_reason",
    )
    rows = []
    for policy in AUTO_POLICIES:
        result = run(replace(scenario, dispatch_policy=policy))
        save_result(result, directory / policy)
        rows.append({field: result.summary[field] for field in columns})
    write_csv(directory / "comparison.csv", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"Saved: {directory.resolve()}")
    return 0 if all(row["success"] for row in rows) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Warehouse simulation with fixed assignments or B0, B1, and P dispatch")
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run", help="Run a fixed instance and save logs")
    execute.add_argument("--instance", type=Path, default=ROOT / "instances" / "single_wide.json")
    execute.add_argument("--policy", choices=AUTO_POLICIES, help="Override the automatic dispatch policy for this instance")
    execute.add_argument("--output", type=Path, help="A NEW output directory; default outputs/run_<timestamp>")
    execute.add_argument("--plot", action="store_true")
    execute.add_argument("--gif", action="store_true", help="Also save animated replay; implies --plot")
    check = commands.add_parser("validate", help="Validate the map and instance")
    check.add_argument("--instance", type=Path, default=ROOT / "instances" / "single_wide.json")
    compare = commands.add_parser("compare", help="Run B0, B1, and P on one instance and save a comparison")
    compare.add_argument("--instance", type=Path, default=ROOT / "instances" / "b0_wide_8.json")
    compare.add_argument("--output", type=Path, help="New directory for the comparison and the three runs")
    batch = commands.add_parser("batch", help="Run the main factorial dispatch experiment")
    batch.add_argument("--output", type=Path, help="New output directory for the experiment")
    batch.add_argument("--seeds", nargs="+", type=int, help="Override the default seeds 0 through 9")
    batch.add_argument("--workers", type=int, default=1, help="Parallel processes, defaults to 1")
    batch_verify = commands.add_parser("batch-verify", help="Replay and verify every saved experiment run")
    batch_verify.add_argument("directory", type=Path)
    batch_verify.add_argument("--workers", type=int, default=1)
    batch_report = commands.add_parser("batch-report", help="Rebuild tables and figures from runs.csv")
    batch_report.add_argument("directory", type=Path)
    for name, description in (("e4", "paired release-time experiment"), ("e5", "small enumeration reference")):
        supplement = commands.add_parser(name, help=f"Run the {description}")
        supplement.add_argument("--output", type=Path, help="New output directory")
        check_supplement = commands.add_parser(f"{name}-verify", help=f"Check the {description} and its tables")
        check_supplement.add_argument("directory", type=Path)
    verify = commands.add_parser("verify", help="Check saved trajectories and replay automatic dispatch and completion times")
    verify.add_argument("run_dir", type=Path)
    replay = commands.add_parser("render", help="Render an existing run, without rerunning simulation")
    replay.add_argument("run_dir", type=Path)
    replay.add_argument("--gif", action="store_true")
    replay.add_argument("--fps", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command in ("e4", "e4-verify", "e5", "e5-verify"):
            if args.command.startswith("e4"):
                from .supplementary import release_experiment as experiment
            else:
                from .reference_experiment import reference_experiment as experiment
            verify_saved = args.command.endswith("-verify")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            directory = args.directory if verify_saved else args.output or ROOT / "outputs" / f"run_{args.command}_{timestamp}"
            counts = experiment(directory, ROOT / "maps", verify_saved)
            print(json.dumps({**counts, "verified": verify_saved, "directory": str(directory.resolve())}, indent=2, ensure_ascii=False))
            return 0
        if args.command == "batch":
            from .experiment_inputs import SEEDS
            from .experiment_report import write_reports
            from .experiments import run_experiment

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            directory = args.output or ROOT / "outputs" / ("run_factorial_" + timestamp)
            rows = run_experiment(directory, ROOT / "maps", args.seeds or SEEDS, args.workers)
            write_reports(directory)
            print(f"Saved {len(rows)} runs and reports in: {directory.resolve()}")
            return 0
        if args.command == "batch-verify":
            from .experiment_report import verify_tables
            from .experiments import verify_experiment

            inputs, runs = verify_experiment(args.directory, args.workers)
            verify_tables(args.directory)
            print(json.dumps({"verified_inputs": inputs, "verified_runs": runs, "tables_ok": True}, indent=2))
            return 0
        if args.command == "batch-report":
            from .experiment_report import write_reports

            write_reports(args.directory)
            print(f"Rebuilt reports in: {args.directory.resolve()}")
            return 0
        if args.command == "validate":
            scenario = load_scenario(args.instance)
            print(f"VALID: {scenario.name}, map={scenario.grid.name}, {scenario.grid.width}x{scenario.grid.height}")
            return 0
        if args.command == "verify":
            directory = args.run_dir
            scenario = load_scenario(directory / "instance.json")
            summary = read_json(directory / "summary.json")
            last_tick = summary["simulation_steps"]
            trace = read_csv(directory / "trajectory.csv")
            result = audit_trajectory(scenario, trace, last_tick)
            if scenario.dispatch_policy != "fixed":
                try:
                    result.update(audit_dispatch(scenario, trace, read_csv(directory / "dispatch.csv"),
                                                 read_csv(directory / "tasks.csv"), last_tick))
                except ValueError as exc:
                    result.update(dispatch_ok=False, dispatch_error=str(exc))
                else:
                    mismatches = [
                        field for field in ("completed_tasks", "makespan", "mean_flow_time")
                        if summary[field] != result[f"recomputed_{field}"]
                    ]
                    result["completion_time_ok"] = not mismatches
                    if mismatches:
                        result["completion_error"] = "summary.json disagrees with trajectory for " + ", ".join(mismatches)
            print(json.dumps(result, indent=2))
            verified = result.get("dispatch_ok", True) and result.get("completion_time_ok", True)
            return 0 if not result["conflict_count"] and verified else 2
        if args.command == "render":
            from .visualize import render
            print(render(args.run_dir, gif=args.gif, fps=args.fps).resolve())
            return 0
        scenario = load_scenario(args.instance)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if args.command == "compare":
            return _compare(scenario, args.output or ROOT / "outputs" / ("run_compare_" + timestamp))
        if args.policy:
            scenario = replace(scenario, dispatch_policy=args.policy, dispatch_order=())
        output = args.output or ROOT / "outputs" / ("run_" + timestamp)
        if output.exists():
            raise FileExistsError(f"Output directory already exists: {output}; choose a new path to retain previous data")
        result = run(scenario)
        save_result(result, output)
        print(json.dumps(result.summary, ensure_ascii=False, indent=2))
        print(f"Saved: {output.resolve()}")
        if args.plot or args.gif:
            from .visualize import render
            render(output, gif=args.gif)
        return 0 if result.summary["success"] else 2
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
