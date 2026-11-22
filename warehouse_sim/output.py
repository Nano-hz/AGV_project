"""Save complete, self-contained evidence for each run."""

import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from . import __version__


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows, fields=None):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields if fields is not None else list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_hashes():
    root = Path(__file__).resolve().parent
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }


def save_result(result, output_dir):
    output_dir = Path(output_dir)
    # Refuse accidental destruction of previous experiment data.
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "instance.json", result.scenario.as_dict())
    write_csv(output_dir / "trajectory.csv", result.trace)
    write_csv(output_dir / "tasks.csv", result.task_rows)
    if result.dispatches is not None:
        fields = [
            "sequence", "time", "task_id", "release_time", "vehicle_id", "pickup_distance", "idle_distances",
        ]
        if result.scenario.dispatch_policy in ("B1", "P"):
            fields.extend(("estimated_finish", "candidates"))
        write_csv(output_dir / "dispatch.csv", result.dispatches, fields)
    write_csv(output_dir / "events.csv", result.events)
    write_json(output_dir / "summary.json", result.summary)
    packages = {}
    for name in ("matplotlib", "numpy", "pillow"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    write_json(output_dir / "metadata.json", {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "simulator_version": __version__, "python": sys.version,
        "executable": sys.executable, "platform": platform.platform(),
        "packages": packages, "source_sha256": source_hashes(),
        "instance_sha256": hashlib.sha256((output_dir / "instance.json").read_bytes()).hexdigest(),
        "time_unit": "abstract_tick", "distance_unit": "grid_cell",
    })


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
