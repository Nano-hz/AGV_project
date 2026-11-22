"""Summarize paired runs and render figures from their saved CSV records."""

from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

from .experiment_inputs import PICKUPS, TASK_COUNTS, VEHICLE_COUNTS
from .experiments import csv_rows
from .models import AUTO_POLICIES
from .output import read_csv, write_csv


def _yes(value):
    return value in (True, "True")


def _time_stats(values):
    return (round(mean(values), 6) if values else None,
            round(stdev(values), 6) if len(values) > 1 else None)


def _summarize(rows):
    completed = [row for row in rows if _yes(row["success"])]
    flow, flow_sd = _time_stats([float(row["mean_flow_time"]) for row in completed])
    span, span_sd = _time_stats([float(row["makespan"]) for row in completed])
    total = sum(int(row["task_count"]) for row in rows)
    handled = sum(int(row["completed_tasks"]) for row in rows)
    vertex = sum(int(row["vertex_conflicts"]) for row in rows)
    swaps = sum(int(row["edge_swap_conflicts"]) for row in rows)
    return {
        "runs": len(rows), "complete_runs": len(completed),
        "full_run_rate": round(len(completed) / len(rows), 8),
        "completed_tasks": handled, "total_tasks": total,
        "task_completion_rate": round(handled / total, 8),
        "mean_flow_time": flow, "sd_flow_time": flow_sd,
        "mean_makespan": span, "sd_makespan": span_sd,
        "timeout_runs": sum(_yes(row["timeout"]) for row in rows),
        "conflict_runs": sum(int(row["conflict_count"]) > 0 for row in rows),
        "vertex_conflicts": vertex, "edge_swap_conflicts": swaps,
    }


def _paired(aware, baseline):
    aware_by_seed = {int(row["seed"]): row for row in aware}
    baseline_by_seed = {int(row["seed"]): row for row in baseline}
    if aware_by_seed.keys() != baseline_by_seed.keys():
        raise ValueError("Unpaired seeds in experiment")
    pairs = [(aware_by_seed[seed], baseline_by_seed[seed]) for seed in sorted(aware_by_seed)]
    matched = [(p, b) for p, b in pairs if _yes(p["success"]) and _yes(b["success"])]

    def improvement(field):
        return _time_stats([100 * (float(b[field]) - float(p[field])) / float(b[field]) for p, b in matched])

    flow, flow_sd = improvement("mean_flow_time")
    span, span_sd = improvement("makespan")
    return {
        "seeds": len(pairs), "paired_complete_runs": len(matched),
        "paired_complete_seeds": " ".join(str(p["seed"]) for p, _ in matched),
        "flow_improvement_pct": flow, "sd_flow_improvement_pct": flow_sd,
        "makespan_improvement_pct": span, "sd_makespan_improvement_pct": span_sd,
        "task_completion_gain_pp": round(100 * mean(float(p["completion_rate"]) - float(b["completion_rate"])
                                                   for p, b in pairs), 6),
    }


def make_tables(rows):
    by_group = defaultdict(list)
    by_policy = defaultdict(list)
    for row in rows:
        key = (row["layout"], int(row["vehicle_count"]), int(row["task_count"]), row["method"])
        by_group[key].append(row)
        by_policy[row["method"]].append(row)
    groups, paired = [], []
    for layout in PICKUPS:
        for vehicles in VEHICLE_COUNTS:
            for tasks in TASK_COUNTS:
                group = {"layout": layout, "vehicle_count": vehicles, "task_count": tasks}
                for policy in AUTO_POLICIES:
                    groups.append({**group, "method": policy, **_summarize(by_group[layout, vehicles, tasks, policy])})
                for baseline in ("B0", "B1"):
                    paired.append({**group, "baseline": baseline, **_paired(
                        by_group[layout, vehicles, tasks, "P"], by_group[layout, vehicles, tasks, baseline],
                    )})
    failures = [row for row in rows if not _yes(row["success"])]
    return {
        "summary.csv": groups,
        "overall.csv": [{"method": policy, **_summarize(by_policy[policy])} for policy in AUTO_POLICIES],
        "paired_summary.csv": paired,
        "failures.csv": failures,
    }


def _figures(root, summary):
    # Match the replay renderer's workspace-local cache and non-interactive backend.
    import os

    cache = Path(__file__).resolve().parents[1] / ".cache" / "matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter

    lookup = {(row["layout"], row["vehicle_count"], row["task_count"], row["method"]): row for row in summary}
    styles = {"B0": ("#2864A0", "o"), "B1": ("#BF642B", "s"), "P": ("#168067", "^")}
    plots = (
        ("mean_flow_time", "sd_flow_time", "Mean task completion time", "Time steps",
         "Each point averages fully completed runs. Whiskers show one sample SD when at least two runs completed."),
        ("mean_makespan", "sd_makespan", "Total completion time", "Time steps",
         "Each point averages fully completed runs. Whiskers show one sample SD when at least two runs completed."),
        ("task_completion_rate", None, "Task completion rate", "Tasks completed",
         "All seeds contribute, including timeouts. Rate = completed tasks divided by submitted tasks."),
    )
    for metric, deviation, title, units, caption in plots:
        fig, axes = plt.subplots(2, 3, sharex=True, sharey=True, figsize=(12, 6.7), facecolor="#F6F8FB")
        fig.subplots_adjust(left=0.095, right=0.98, top=0.80, bottom=0.15, wspace=0.16, hspace=0.38)
        fig.text(0.095, 0.935, title, fontsize=23, fontweight="bold", color="#142737")
        fig.legend(
            handles=[Line2D([0], [0], color=color, marker=marker, label=policy, linewidth=2)
                     for policy, (color, marker) in styles.items()],
            loc="upper right", bbox_to_anchor=(0.98, 0.939), ncol=3, frameon=False,
        )
        for row_index, vehicles in enumerate(VEHICLE_COUNTS):
            for col_index, layout in enumerate(PICKUPS):
                axis = axes[row_index, col_index]
                axis.set_facecolor("white")
                axis.set_title(f"{layout.title()}  ·  {vehicles} AGVs", loc="left", fontsize=11, color="#142737", pad=8)
                axis.yaxis.grid(color="#E2E8EF")
                axis.set_axisbelow(True)
                axis.spines[["top", "right"]].set_visible(False)
                axis.spines[["left", "bottom"]].set_color("#B2BECA")
                axis.tick_params(colors="#334959", labelbottom=True)
                axis.set_xticks(TASK_COUNTS)
                axis.set_xlim(5.7, 26.3)
                if col_index == 0:
                    axis.set_ylabel(units)
                if deviation is None:
                    axis.yaxis.set_major_formatter(PercentFormatter(1))
                    axis.set_ylim(0, 1.07)
                for offset, (policy, (color, marker)) in zip((-0.36, 0, 0.36), styles.items()):
                    entries = [lookup[layout, vehicles, tasks, policy] for tasks in TASK_COUNTS]
                    x_values = [tasks + offset for tasks in TASK_COUNTS]
                    axis.plot(x_values, [entry[metric] for entry in entries], color=color, marker=marker, lw=1.8, ms=5)
                    if deviation is not None:
                        for x, entry in zip(x_values, entries):
                            if entry[deviation] is not None:
                                y, error = entry[metric], entry[deviation]
                                axis.errorbar(x, y, yerr=[[min(y, error)], [error]], color=color, capsize=2.6,
                                              linewidth=1, fmt="none", alpha=0.72)
        fig.text(0.54, 0.085, "Tasks per run", ha="center", fontsize=11, color="#142737")
        fig.text(0.095, 0.039, caption, color="#455A6B", fontsize=9)
        fig.savefig(root / f"{metric}.png", dpi=180)
        plt.close(fig)


def write_reports(root):
    root = Path(root)
    rows = read_csv(root / "runs.csv")
    tables = make_tables(rows)
    for filename, table in tables.items():
        # Preserve the failures header even when every run succeeded.
        write_csv(root / filename, table, fields=list(rows[0]) if filename == "failures.csv" else None)
    _figures(root, tables["summary.csv"])
    return tables


def verify_tables(root):
    root = Path(root)
    rows = read_csv(root / "runs.csv")
    for filename, table in make_tables(rows).items():
        if read_csv(root / filename) != csv_rows(table):
            raise ValueError(f"{filename} disagrees with runs.csv")
