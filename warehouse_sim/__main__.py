"""CLI for running, validating, and inspecting warehouse simulations."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from .collisions import audit_trajectory
from .dispatch_audit import audit_dispatch
from .models import load_scenario, read_json
from .output import read_csv, save_result
from .simulator import run

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Warehouse simulation with fixed assignments or B0 dispatch")
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run", help="Run a fixed instance and save logs")
    execute.add_argument("--instance", type=Path, default=ROOT / "instances" / "single_wide.json")
    execute.add_argument("--output", type=Path, help="A NEW output directory; default outputs/run_<timestamp>")
    execute.add_argument("--plot", action="store_true")
    execute.add_argument("--gif", action="store_true", help="Also save animated replay; implies --plot")
    check = commands.add_parser("validate", help="Validate the map and instance")
    check.add_argument("--instance", type=Path, default=ROOT / "instances" / "single_wide.json")
    verify = commands.add_parser("verify", help="Check saved trajectories and, for B0, replay dispatch decisions")
    verify.add_argument("run_dir", type=Path)
    replay = commands.add_parser("render", help="Render an existing run, without rerunning simulation")
    replay.add_argument("run_dir", type=Path)
    replay.add_argument("--gif", action="store_true")
    replay.add_argument("--fps", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            scenario = load_scenario(args.instance)
            print(f"VALID: {scenario.name}, map={scenario.grid.name}, {scenario.grid.width}x{scenario.grid.height}")
            return 0
        if args.command == "verify":
            directory = args.run_dir
            scenario = load_scenario(directory / "instance.json")
            last_tick = read_json(directory / "summary.json")["simulation_steps"]
            trace = read_csv(directory / "trajectory.csv")
            result = audit_trajectory(scenario, trace, last_tick)
            if scenario.dispatch_policy == "B0":
                try:
                    result.update(audit_dispatch(scenario, trace, read_csv(directory / "dispatch.csv"),
                                                 read_csv(directory / "tasks.csv"), last_tick))
                except ValueError as exc:
                    result.update(dispatch_ok=False, dispatch_error=str(exc))
            print(json.dumps(result, indent=2))
            return 2 if result["conflict_count"] or not result.get("dispatch_ok", True) else 0
        if args.command == "render":
            from .visualize import render
            print(render(args.run_dir, gif=args.gif, fps=args.fps).resolve())
            return 0
        scenario = load_scenario(args.instance)
        output = args.output or ROOT / "outputs" / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
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
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
