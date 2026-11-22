"""静态网格寻路。

广度优先搜索计算到目标的距离表，A* 则返回给定起点和终点之间的具体路线。
派单可用这些静态距离评分，时空搜索也可用它们估计剩余路程。
"""

from collections import deque
from heapq import heappop, heappush
from itertools import count

from ..models import Cell, GridMap


def manhattan(a: Cell, b: Cell) -> int:
    """计算两格之间的曼哈顿距离，作为四连通网格上的步数下界。"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def distances_to(grid: GridMap, goal: Cell, blocked=frozenset()) -> dict[Cell, int]:
    """从目标反向做广度优先搜索，返回所有可达格到该目标的最短步数。"""
    if goal in blocked:
        return {}
    distances, queue = {goal: 0}, deque([goal])
    while queue:
        cell = queue.popleft()
        for neighbor in grid.neighbors(cell):
            # 单步代价相同，格子第一次入队时的距离即为最短距离。
            if neighbor not in blocked and neighbor not in distances:
                distances[neighbor] = distances[cell] + 1
                queue.append(neighbor)
    return distances


def shortest_path(grid: GridMap, start: Cell, goal: Cell) -> list[Cell] | None:
    """用静态 A* 找到包含起终点的最短路线，无法到达时返回 None。"""
    if not grid.walkable(start) or not grid.walkable(goal):
        return None
    order = count()
    # 优先展开已走步数加估计剩余步数最小的节点，同分时按入队顺序处理。
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
