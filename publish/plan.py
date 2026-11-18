"""整单分卷规划。

每行成本为一加该行的实际测点数（两列都缺值的测点仍占槽计数）。
每个工位按给定顺序恰领一个非空连续行段，合起来恰好覆盖整个窗口；
卷成本为段内行成本之和，不得超过该工位自己的上限。分卷最小化最重
卷成本，同峰值取字典序最小的内部切点。这里的切点按窗口内的相对行
位置计，由签发方换算为原修订行位置。
"""

from layout.shape import FurnaceRow, row_slot_count


def row_costs(rows: tuple[FurnaceRow, ...]) -> list[int]:
    """One plus the actual point count of each row."""
    return [1 + row_slot_count(row) for row in rows]


def plan_cuts(costs, caps) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Plan window-relative internal cuts for the given row costs and caps.

    Return ``(cuts, segment_costs)`` minimizing the heaviest segment, with
    ties broken by the lexicographically smallest cut list, or ``None``
    when no partition stays within every station cap.
    """
    n = len(costs)
    k = len(caps)
    if k > n:
        return None
    prefix = [0]
    for cost in costs:
        prefix.append(prefix[-1] + cost)

    def segment(first: int, last: int) -> int:
        return prefix[last] - prefix[first]

    # best[station][first] is the minimal achievable peak for covering rows
    # first..n-1 with stations station..k-1, or None when infeasible.
    best = [[None] * (n + 1) for _ in range(k + 1)]
    best[k][n] = 0
    for station in range(k - 1, -1, -1):
        least_rows = k - station
        for first in range(0, n - least_rows + 1):
            chosen = None
            for last in range(first + 1, n - (least_rows - 1) + 1):
                rest = best[station + 1][last]
                if rest is None:
                    continue
                cost = segment(first, last)
                if cost > caps[station]:
                    break
                peak = max(cost, rest)
                if chosen is None or peak < chosen:
                    chosen = peak
            best[station][first] = chosen
    peak = best[0][0]
    if peak is None:
        return None

    cuts = []
    first = 0
    for station in range(k):
        least_rows = k - station
        for last in range(first + 1, n - (least_rows - 1) + 1):
            cost = segment(first, last)
            if cost > caps[station] or cost > peak:
                break
            rest = best[station + 1][last]
            if rest is not None and rest <= peak:
                if station < k - 1:
                    cuts.append(last)
                first = last
                break
        else:
            raise RuntimeError('optimal partition reconstruction failed')
    boundaries = [0, *cuts, n]
    segment_costs = tuple(segment(earlier, later) for earlier, later in zip(boundaries, boundaries[1:]))
    return tuple(cuts), segment_costs
