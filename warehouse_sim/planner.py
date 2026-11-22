"""Deterministic static A*. This is NOT a multi-vehicle collision planner."""

from collections import deque
from heapq import heappop, heappush
from itertools import count

from .models import Cell, GridMap


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def distances_to(grid: GridMap, goal: Cell, blocked=frozenset()) -> dict[Cell, int]:
    """Static shortest distances to one goal, computed by breadth-first search."""
    if goal in blocked:
        return {}
    distances, queue = {goal: 0}, deque([goal])
    while queue:
        cell = queue.popleft()
        for neighbor in grid.neighbors(cell):
            if neighbor not in blocked and neighbor not in distances:
                distances[neighbor] = distances[cell] + 1
                queue.append(neighbor)
    return distances


def shortest_path(grid: GridMap, start: Cell, goal: Cell) -> list[Cell] | None:
    """Return both endpoints, or None if no static route exists."""
    if not grid.walkable(start) or not grid.walkable(goal):
        return None
    order = count()
    frontier = [(manhattan(start, goal), next(order), 0, start)]
    distance, parent = {start: 0}, {}
    while frontier:
        _, _, cost, here = heappop(frontier)
        if cost != distance[here]:
            continue
        if here == goal:
            path = [here]
            while here in parent:
                here = parent[here]
                path.append(here)
            return list(reversed(path))
        for neighbor in grid.neighbors(here):
            new_cost = cost + 1
            if new_cost < distance.get(neighbor, float("inf")):
                distance[neighbor], parent[neighbor] = new_cost, here
                heappush(frontier, (new_cost + manhattan(neighbor, goal), next(order), new_cost, neighbor))
    return None
