"""Combine cycle factors: standardized weighted composites, phase alignment and lead/lag.

Composites add standardized factor paths (observed history, then each factor's
preferred-fit projection). Alignment is the weighted phase coherence of the
fitted cycles (1 = all cycles at the same phase, 0 = phases cancel). Lead/lag
correlations of autocorrelated series overstate significance and imply no causation.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

from . import fitting
from .fitting import TAU, Z80, _r, phase_label, to_date

ALIGNED = 0.8
MAX_POINTS = 5000


def _path(state: dict, factor_id: str, grid: np.ndarray) -> dict:
    from . import phases_at, preferred_fit, series_points

    points, revision, _ = series_points(state, factor_id)
    if len(points) < 2:
        raise fitting.InsufficientData(f"{factor_id}: needs observations at two or more dates")
    t = np.array([p[0] for p in points])
    y = np.array([p[1] for p in points])
    unique, inverse = np.unique(t, return_inverse=True)
    y = np.bincount(inverse, weights=y) / np.bincount(inverse)
    mean, sd = float(y.mean()), float(y.std()) or 1.0
    fit, status = preferred_fit(state, factor_id, revision)
    value = np.full(len(grid), np.nan)
    variance = np.zeros(len(grid))
    observed = (grid >= unique[0]) & (grid <= unique[-1])
    value[observed] = np.interp(grid[observed], unique, y)
    if fit is not None:
        projection = fit["projection"]
        pt = np.array(projection["t"])
        future = (grid > unique[-1]) & (grid <= pt[-1])
        value[future] = np.interp(grid[future], pt, np.array(projection["mean"], dtype=float))
        spread = (np.array(projection["upper"], dtype=float) - np.array(projection["lower"], dtype=float)) / (2 * Z80)
        variance[future] = np.interp(grid[future], pt, spread) ** 2
    phase = np.full(len(grid), np.nan)
    if fit is not None:
        for i, when in enumerate(grid):
            found = phases_at(fit, float(when))
            if found:
                phase[i] = found[0]
    return {
        "z": (value - mean) / sd,
        "var": variance / sd**2,
        "observed": observed,
        "phase": phase,
        "fit": fit,
        "fit_status": status,
        "last": float(unique[-1]),
    }


def _windows(grid, strength, mean_phase, counts, start_at: float) -> list[dict]:
    windows, current = [], None
    for i, when in enumerate(grid):
        aligned = when >= start_at and counts[i] >= 2 and strength[i] >= ALIGNED
        if aligned and current is None:
            current = {"start": i, "best": i}
        if aligned and strength[i] > strength[current["best"]]:
            current["best"] = i
        if current is not None and (not aligned or i == len(grid) - 1):
            end = i if aligned else i - 1
            best = current["best"]
            windows.append({
                "start": to_date(grid[current["start"]]),
                "end": to_date(grid[end]),
                "max_alignment": _r(strength[best], 3),
                "shared_phase": phase_label(mean_phase[best]),
                "at": to_date(grid[best]),
            })
            current = None
    return windows


def _lead_lag(names: list[str], series: list[np.ndarray], step: float, max_lag_years: float = 30) -> list[dict]:
    out = []
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            a, b = series[i], series[j]
            overlap = int(np.sum(~np.isnan(a) & ~np.isnan(b)))
            limit = int(min(max_lag_years, overlap * step / 3) / step)
            found = []
            for k in range(-limit, limit + 1):
                x, y = (a[: len(a) - k], b[k:]) if k >= 0 else (a[-k:], b[: len(b) + k])
                mask = ~np.isnan(x) & ~np.isnan(y)
                if mask.sum() < 10 or np.std(x[mask]) == 0 or np.std(y[mask]) == 0:
                    continue
                found.append((k, float(np.corrcoef(x[mask], y[mask])[0, 1]), int(mask.sum())))
            if not found:
                continue
            # Periodic series correlate almost equally at in-phase and anti-phase lags; prefer the shortest.
            strongest = max(abs(r) for _, r, _ in found)
            best = min((f for f in found if abs(f[1]) >= strongest - 0.05), key=lambda f: (abs(f[0]), -abs(f[1])))
            years = best[0] * step
            size = abs(best[1])
            strength = "negligible" if size < 0.3 else "weak" if size < 0.5 else "moderate" if size < 0.7 else "strong"
            relation = "move together" if best[0] == 0 else (f"{names[i]} leads {names[j]} by {abs(years):.3g} years" if years > 0 else f"{names[j]} leads {names[i]} by {abs(years):.3g} years")
            if best[1] < 0:
                relation += " (inversely)"
            out.append({
                "a": names[i],
                "b": names[j],
                "lag_years": _r(years),
                "correlation": _r(best[1], 3),
                "strength": strength,
                "overlap_points": best[2],
                "relation": "no meaningful lead/lag relationship" if strength == "negligible" else relation,
            })
    return out


def combine(state: dict, components: list[dict], *, start: date | None = None, end: date | None = None, at: date | None = None, step: float = 1.0, include_paths: bool = False, lead_lag: bool = True) -> dict:
    from . import series_points

    if not components:
        raise ValueError("Provide at least one component")
    for component in components:
        if component["factor_id"] not in state["factors"]:
            raise KeyError(f"Cycle factor not found: {component['factor_id']}")
    spans = []
    for component in components:
        points = series_points(state, component["factor_id"])[0]
        if len(points) < 2:
            raise fitting.InsufficientData(f"{component['factor_id']}: needs observations at two or more dates")
        spans.append((points[0][0] + component["lag_years"], points[-1][0] + component["lag_years"]))
    t_start = fitting.decimal_year(start) if start else min(s for s, _ in spans)
    horizon = max(
        ((state["fits"].get(_preferred_id(state, c["factor_id"])) or {}).get("projection", {}).get("t", [s[1]])[-1] + c["lag_years"])
        for c, s in zip(components, spans)
    )
    t_end = fitting.decimal_year(end) if end else horizon
    if t_end <= t_start:
        raise ValueError("Combination window is empty")
    step = max(step, (t_end - t_start) / MAX_POINTS)
    grid = np.arange(t_start, t_end + step / 2, step)
    total = sum(abs(c["weight"]) for c in components)
    acc, cover, var = np.zeros(len(grid)), np.zeros(len(grid)), np.zeros(len(grid))
    vectors, counts = np.zeros(len(grid), dtype=complex), np.zeros(len(grid))
    weight_sum = np.zeros(len(grid))
    details, raw, lasts, paths = [], [], [], []
    for component in components:
        weight, lag = component["weight"], component["lag_years"]
        path = _path(state, component["factor_id"], grid - lag)
        present = ~np.isnan(path["z"])
        acc[present] += weight * path["z"][present]
        cover[present] += abs(weight)
        var[present] += weight**2 * path["var"][present]
        phased = ~np.isnan(path["phase"])
        shifted = path["phase"][phased] + (math.pi if weight < 0 else 0)
        vectors[phased] += abs(weight) * np.exp(1j * shifted)
        weight_sum[phased] += abs(weight)
        counts[phased] += 1
        unshifted = path if lag == 0 else _path(state, component["factor_id"], grid)
        raw.append(np.where(unshifted["observed"], unshifted["z"], np.nan))
        lasts.append(path["last"] + lag)
        paths.append({"factor_id": component["factor_id"], "name": state["factors"][component["factor_id"]]["name"], "z": _r(path["z"] * (1 if weight > 0 else -1))})
        fit = path["fit"]
        details.append({
            "factor_id": component["factor_id"],
            "name": state["factors"][component["factor_id"]]["name"],
            "weight": weight,
            "lag_years": lag,
            "fit_id": fit["id"] if fit else None,
            "fit_status": path["fit_status"],
            "verdict": fit["verdict"] if fit else None,
            "last_observation": to_date(path["last"]),
        })
    usable = cover >= 0.5 * total
    with np.errstate(invalid="ignore", divide="ignore"):
        composite = np.where(usable, acc / cover, np.nan)
        sd = np.where(usable, np.sqrt(var) / cover, np.nan)
        # Coherence of a single phased component is trivially 1; alignment needs at least two.
        strength = np.where((weight_sum > 0) & (counts >= 2), np.abs(vectors) / np.where(weight_sum > 0, weight_sum, 1), np.nan)
    mean_phase = np.angle(vectors) % TAU
    last_observed = max(lasts)
    future = grid > last_observed
    finite = ~np.isnan(composite)
    turning = fitting.turning_points(grid[future & finite], composite[future & finite]) if np.sum(future & finite) >= 3 else []
    result = {
        "components": details,
        "method": "Weighted mean of standardized factor paths (observed data, then preferred-fit projections). Interval assumes independent components.",
        "grid": {"start": to_date(grid[0]), "end": to_date(grid[-1]), "step_years": _r(step)},
        "series": {"t": _r(grid), "value": _r(composite), "lower": _r(composite - Z80 * sd), "upper": _r(composite + Z80 * sd), "alignment": _r(strength, 4), "coverage": _r(cover / total, 3), "projected": [bool(x) for x in future]},
        "upcoming_turning_points": [{"type": p["type"], "date": to_date(p["t"]), "value": _r(p["value"])} for p in turning[:4]],
        "alignment_windows": _windows(grid, np.nan_to_num(strength), mean_phase, counts, last_observed),
        "lead_lag": _lead_lag([d["factor_id"] for d in details], raw, step) if lead_lag else [],
        "notes": [
            "Alignment near 1 means the fitted cycles share a phase, so their swings reinforce; it is not a probability.",
            "Lead/lag correlations between autocorrelated series overstate significance and do not establish causation.",
        ],
    }
    if any(d["verdict"] not in ("supported", None) for d in details):
        result["notes"].append("Some components have weak or under-identified fits; the composite inherits that uncertainty.")
    if include_paths:
        result["component_paths"] = paths
    if at is not None:
        t = fitting.decimal_year(at)
        if grid[0] <= t <= grid[-1]:
            index = int(np.argmin(np.abs(grid - t)))

            def at_t(values):  # linear interpolation between grid points, not the nearest point
                finite = ~np.isnan(values)
                return float(np.interp(t, grid[finite], values[finite])) if finite.sum() >= 2 else float("nan")

            value, spread = at_t(composite), at_t(sd)
            vector = at_t(vectors.real) + 1j * at_t(vectors.imag)
            weight = at_t(weight_sum)
            result["at"] = {
                "date": at.isoformat(),
                "value": _r(value),
                "lower": _r(value - Z80 * spread),
                "upper": _r(value + Z80 * spread),
                "alignment": _r(abs(vector) / weight, 3) if counts[index] >= 2 and weight > 0 else None,
                "shared_phase": phase_label(np.angle(vector) % TAU) if counts[index] >= 2 else None,
                "projected": bool(t > last_observed),
            }
        else:
            result["at"] = {"date": at.isoformat(), "relation": "outside the combination window"}
    return result


def _preferred_id(state: dict, factor_id: str) -> str | None:
    from . import preferred_fit

    fit = preferred_fit(state, factor_id)[0]
    return fit["id"] if fit else None


def composite_outlook(state: dict, composite: dict, at: date | None) -> dict:
    entry = {"composite_id": composite["id"], "name": composite["name"], "components": composite["components"], "entity_ids": composite["entity_ids"]}
    try:
        result = combine(state, composite["components"], at=at, step=0.25, lead_lag=False)
    except (fitting.InsufficientData, ValueError) as exc:
        return {**entry, "note": str(exc)}
    entry.update(
        at=result.get("at"),
        upcoming_turning_points=result["upcoming_turning_points"][:2],
        alignment_windows=result["alignment_windows"][:3],
        component_fits=[{k: d[k] for k in ("factor_id", "fit_id", "verdict", "fit_status")} for d in result["components"]],
        notes=result["notes"],
    )
    return entry
