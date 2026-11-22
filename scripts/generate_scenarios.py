"""Recreate the three fixed 20x20 development maps and stage 1 instances."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_map(name):
    grid = [["#" if x in (0, 19) or y in (0, 19) else "." for x in range(20)] for y in range(20)]

    def shelf(x0, x1, y0, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                grid[y][x] = "#"

    if name == "wide":
        for x0, x1 in ((4, 6), (10, 12)):
            for y0, y1 in ((3, 5), (9, 11), (15, 16)):
                shelf(x0, x1, y0, y1)
        pickups = [(7, 4), (13, 4), (7, 10), (13, 10), (7, 15), (13, 15)]
        selected = (7, 10)
    elif name == "narrow":
        for x0, x1 in ((3, 6), (8, 11), (13, 16)):
            for y0, y1 in ((2, 7), (9, 16)):
                shelf(x0, x1, y0, y1)
        pickups = [(7, 4), (12, 4), (17, 4), (7, 12), (12, 12), (17, 12)]
        selected = (7, 12)
    elif name == "bottleneck":
        shelf(10, 10, 1, 18)
        grid[10][10] = "."
        for x0, x1 in ((4, 6), (13, 15)):
            for y0, y1 in ((3, 7), (12, 16)):
                shelf(x0, x1, y0, y1)
        pickups = [(7, 4), (7, 14), (16, 4), (16, 14)]
        selected = (7, 4)
    else:
        raise ValueError(name)
    for symbol, points in (("P", [(1, y) for y in (3, 7, 12, 16)]), ("U", pickups), ("D", [(18, y) for y in (3, 7, 12, 16)])):
        for x, y in points:
            if grid[y][x] != ".":
                raise ValueError(f"Role overlaps obstacle or endpoint: {name}, {(x,y)}")
            grid[y][x] = symbol
    return {"schema_version": 1, "name": name, "grid": ["".join(row) for row in grid]}, selected


def main():
    for name in ("wide", "narrow", "bottleneck"):
        grid, pickup = make_map(name)
        save(ROOT / "maps" / f"{name}.json", grid)
        save(ROOT / "instances" / f"single_{name}.json", {
            "schema_version": 1, "name": f"single_{name}", "seed": 0,
            "map": f"../maps/{name}.json",
            "parameters": {"pickup_steps": 1, "dropoff_steps": 1, "max_steps": 1000},
            "vehicles": [{"id": "AGV-01", "start": [1, 3]}],
            "tasks": [{"id": "T001", "release_time": 0, "pickup": list(pickup), "delivery": [18, 16]}],
        })
        print(f"Generated: {name}")


if __name__ == "__main__":
    main()
