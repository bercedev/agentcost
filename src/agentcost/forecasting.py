"""Cost forecasting from daily spend history (standard library only)."""

from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from statistics import linear_regression, mean
from typing import Dict, Iterable, List, Optional, Tuple

from agentcost.cost import TokenUsage, calculate_cost

MIN_HISTORY_DAYS = 3
SEASONALITY_MIN_DAYS = 14  # two full weeks are needed to trust a weekly pattern
Z_95 = 1.96  # multiplier for an approximate 95% range


@dataclass
class ForecastPoint:
    """Projected cost for one future day, with a likely range."""
    day: date
    cost: float
    low: float
    high: float


@dataclass
class Forecast:
    points: List[ForecastPoint]
    history_days: int
    daily_slope: float
    std_error: float
    seasonal: bool

    def total(self, days: Optional[int] = None) -> Tuple[float, float, float]:
        """Projected (total, low, high) for the first `days` forecast days.

        The range assumes independent daily errors, so its margin grows with
        sqrt(days). It is approximate.
        """
        pts = self.points[:days] if days else self.points
        mid = sum(p.cost for p in pts)
        margin = Z_95 * self.std_error * sqrt(len(pts))
        return mid, max(0.0, mid - margin), mid + margin


def daily_costs_by_date(usages: Iterable[TokenUsage]) -> Dict[date, float]:
    """Sum cost per calendar day. Usages without a timestamp are skipped."""
    totals: Dict[date, float] = {}
    for u in usages:
        if u.timestamp is None:
            continue
        day = u.timestamp.date()
        totals[day] = totals.get(day, 0.0) + calculate_cost(u)
    return totals


def fill_daily(costs_by_day: Dict[date, float], start: date, end: date) -> List[float]:
    """One value per day from start to end inclusive; days with no usage are 0.0."""
    n = (end - start).days + 1
    return [costs_by_day.get(start + timedelta(days=i), 0.0) for i in range(n)]


def forecast(daily_costs: List[float], start: date, horizon: int) -> Forecast:
    """Fit a linear trend (plus a day-of-week pattern with >= 14 days of data).

    `daily_costs[0]` is the cost on `start`; one value per consecutive day.
    """
    n = len(daily_costs)
    if n < MIN_HISTORY_DAYS:
        raise ValueError(
            f"Need at least {MIN_HISTORY_DAYS} days of history to forecast, got {n}"
        )
    if horizon < 1:
        raise ValueError("Forecast horizon must be at least 1 day")

    xs = list(range(n))
    fit = linear_regression(xs, daily_costs)

    def trend(x: int) -> float:
        return fit.intercept + fit.slope * x

    resid = [y - trend(x) for x, y in zip(xs, daily_costs)]

    season = [0.0] * 7
    seasonal = n >= SEASONALITY_MIN_DAYS
    if seasonal:
        w0 = start.weekday()
        for k in range(7):
            season[k] = mean(r for x, r in zip(xs, resid) if (w0 + x) % 7 == k)
        resid = [r - season[(w0 + x) % 7] for x, r in zip(xs, resid)]

    dof = n - 2 - (6 if seasonal else 0)
    std_error = sqrt(sum(r * r for r in resid) / dof)

    points: List[ForecastPoint] = []
    for d in range(1, horizon + 1):
        x = n - 1 + d
        day = start + timedelta(days=x)
        mid = max(0.0, trend(x) + season[day.weekday()])
        points.append(
            ForecastPoint(
                day=day,
                cost=mid,
                low=max(0.0, mid - Z_95 * std_error),
                high=mid + Z_95 * std_error,
            )
        )
    return Forecast(points, n, fit.slope, std_error, seasonal)