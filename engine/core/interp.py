from __future__ import annotations


def lerp(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    """Linear interpolation between (x0,y0) and (x1,y1) at x."""
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def interp_piecewise_linear(xs: list[float], ys: list[float], x: float) -> float:
    """
    Piecewise linear interpolation. Assumes xs sorted ascending.
    Clamps to endpoints.
    """
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("xs and ys must be same length and have at least 2 points.")

    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]

    for i in range(1, len(xs)):
        if x <= xs[i]:
            return lerp(xs[i - 1], ys[i - 1], xs[i], ys[i], x)

    return ys[-1]
