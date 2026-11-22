"""Render saved logs only; rendering never advances the simulator."""

import os
from collections import defaultdict
from pathlib import Path

from .models import load_scenario, read_json
from .output import read_csv


def render(run_dir, gif=False, fps=5):
    if fps <= 0:
        raise ValueError("fps must be positive")
    run_dir = Path(run_dir)
    scenario = load_scenario(run_dir / "instance.json")
    summary = read_json(run_dir / "summary.json")
    trace = read_csv(run_dir / "trajectory.csv")
    # Keep Matplotlib's writable cache inside the project; no GUI required.
    cache = Path(__file__).resolve().parents[1] / ".cache" / "matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from matplotlib.colors import ListedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    grid = scenario.grid
    colors = {"floor": "#F7F8FA", "wall": "#344256", "route": "#007F88", "loaded": "#CE6A25"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(10.4, 8.6), dpi=120)
    fig.subplots_adjust(left=0.08, right=0.73, bottom=0.10, top=0.87)
    ax.imshow([[int(c == "#") for c in row] for row in grid.rows], cmap=ListedColormap([colors["floor"], colors["wall"]]), vmin=0, vmax=1, origin="upper")
    ax.set_xticks(range(grid.width))
    ax.set_yticks(range(grid.height))
    ax.set_xticks([x - 0.5 for x in range(grid.width + 1)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(grid.height + 1)], minor=True)
    ax.grid(which="minor", color="#DCE2E9", linewidth=0.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.tick_params(which="major", labelsize=8, length=0)
    ax.set_xlabel("x / grid cells")
    ax.set_ylabel("y / grid cells")
    ax.set_xlim(-0.5, grid.width - 0.5)
    ax.set_ylim(grid.height - 0.5, -0.5)
    markers = [("P", "s", "#4470AA", "Parking"), ("U", "^", "#007F88", "Pickup"), ("D", "v", "#CE6A25", "Delivery")]
    for symbol, marker, color, label in markers:
        cells = grid.cells(symbol)
        ax.scatter([p[0] for p in cells], [p[1] for p in cells], marker=marker, c=color, s=65, zorder=3, label=label)
    by_vehicle = defaultdict(list)
    for row in trace:
        by_vehicle[row["vehicle_id"]].append(row)
    vehicle_ids = sorted(by_vehicle)
    multi = len(vehicle_ids) == 2
    route_colors = [colors["route"], "#8251A0"]
    tracks = {}
    for vehicle_id, color in zip(vehicle_ids, route_colors):
        rows = sorted(by_vehicle[vehicle_id], key=lambda row: int(row["time"]))
        xs, ys = [int(row["x"]) for row in rows], [int(row["y"]) for row in rows]
        line, = ax.plot(xs, ys, color=color, linewidth=2.5, alpha=0.88, zorder=4)
        tracks[vehicle_id] = (rows, xs, ys, line, color)
    if multi:
        points = [(vehicle.start, vehicle.id) for vehicle in scenario.vehicles]
    else:
        points = [(scenario.vehicles[0].start, "START"), (scenario.tasks[0].pickup, "PICKUP"), (scenario.tasks[0].delivery, "END")]
    for pos, label in points:
        left = pos[0] > grid.width * 0.65
        ax.annotate(label, xy=pos, xytext=(-7 if left else 7, -12), textcoords="offset points", ha="right" if left else "left", fontsize=8, weight="bold", color="#203047", bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9, "pad": 2}, zorder=7)
    title = f"WAREHOUSE AGV / STAGE {summary['stage']}"
    fig.text(0.08, 0.965, title, fontsize=20, weight="bold", color="#203047", va="top")
    description = "2 vehicles, 2 tasks  |  space-time A*" if multi else "1 vehicle, 1 task  |  static A*"
    if scenario.dispatch_policy == "B0":
        description = f"{len(vehicle_ids)} vehicles, {len(scenario.tasks)} tasks  |  B0 + space-time A*"
    fig.text(0.08, 0.922, f"{grid.name.replace('_', ' ').title()}  |  {description}", color="#64748B", fontsize=11)
    legend = [Patch(facecolor=colors["wall"], label="Shelf / wall")]
    legend += [Line2D([0], [0], marker=m, color="none", markerfacecolor=c, markeredgecolor=c, markersize=8, label=l) for _, m, c, l in markers]
    legend += [Line2D([0], [0], color=track[-1], linewidth=2.5, label=vehicle_id if multi else "Saved trajectory") for vehicle_id, track in tracks.items()]
    fig.legend(handles=legend, loc="upper left", bbox_to_anchor=(0.75, 0.86), frameon=False, fontsize=10, labelspacing=1.2)
    metrics = (
        f"{'COMPLETED' if summary['success'] else 'INCOMPLETE'}\n\n"
        f"Elapsed    {summary['simulation_steps']} ticks\n"
        f"Travel      {summary['total_distance']} cells\n"
        f"Service    {summary['total_service_steps']} ticks\n"
        f"Waiting    {summary['total_wait_steps']} ticks\n\n"
        + (f"Conflicts   {summary['conflict_count']}\nFilled dot: carrying" if multi else "Origin: top left\nOne move per tick\nPickup / dropoff:\n1 tick each by default")
    )
    fig.text(0.77, 0.52, metrics, va="top", fontsize=10, linespacing=1.7, color="#334155")
    fig.text(0.08, 0.035, "Rendered from trajectory.csv. Simulation time is measured in abstract ticks.", fontsize=9, color="#64748B")
    fig.savefig(run_dir / "trajectory.png", dpi=160, facecolor="white")
    if gif:
        # PNG stays a complete trajectory; GIF only reveals the path so far.
        vehicles = {}
        for vehicle_id, track in tracks.items():
            dot, = ax.plot([], [], "o", markersize=10, markeredgecolor=track[-1], markeredgewidth=2, zorder=6)
            vehicles[vehicle_id] = dot
        clock = ax.set_title("", loc="left", fontsize=10, pad=10)

        def update(index):
            actions = []
            for vehicle_id, (rows, xs, ys, line, color) in tracks.items():
                row = rows[index]
                line.set_data(xs[:index + 1], ys[:index + 1])
                dot = vehicles[vehicle_id]
                dot.set_data([xs[index]], [ys[index]])
                dot.set_markerfacecolor(color if int(row["loaded"]) else "white")
                if scenario.dispatch_policy == "B0":
                    actions.append(f"{vehicle_id} {row['task_id'] or '-'}: {row['action']}")
                else:
                    actions.append(f"{vehicle_id}: {row['action']}" if multi else f"{row['action']}   |   {row['phase']}")
            clock.set_text(f"t = {index}   |   " + "   |   ".join(actions))

        animation = FuncAnimation(fig, update, frames=summary["simulation_steps"] + 1, interval=1000 / fps, blit=False)
        animation.save(run_dir / "replay.gif", writer=PillowWriter(fps=fps), dpi=85)
    plt.close(fig)
    return run_dir / "trajectory.png"
