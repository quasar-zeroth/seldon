"""Deterministic cycle models over dated series. Pure numpy; no database, provider or network.

Times are decimal years. Random draws (red-noise surrogates, parameter uncertainty)
use a caller-supplied seed derived from data and specification digests, so a fit
is reproducible. See docs/cycles.md for the modelling rationale and limits.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

ALGORITHM_VERSION = "2"  # 2: projections and baselines anchored by AR(1) residual persistence
Z80 = 1.2815515655446004  # two-sided 80% normal interval
TAU = 2 * math.pi
QUADRANTS = ("peak", "declining", "trough", "rising")
DRAWS = 300


class InsufficientData(ValueError):
    """The series cannot identify the requested model."""


def decimal_year(value: date) -> float:
    start = date(value.year, 1, 1)
    days = 366 if calendar.isleap(value.year) else 365
    return value.year + (value - start).days / days


def to_date(t: float) -> str:
    year = min(max(int(math.floor(t)), 1), 9999)
    days = 366 if calendar.isleap(year) else 365
    offset = min(max(int(round((t - year) * days)), 0), days - 1)
    return (date(year, 1, 1) + timedelta(days=offset)).isoformat()


def phase_label(phi: float) -> str:
    """phi=0 is the peak of the cyclical component; phase advances with time."""
    return QUADRANTS[int(((phi % TAU) + math.pi / 4) % TAU // (math.pi / 2))]


def _r(value, digits: int = 6):
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return [_r(v, digits) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_r(v, digits) for v in value]
    value = float(value)
    if not math.isfinite(value):
        return None
    return float(f"{value:.{digits}g}")


@dataclass
class Series:
    t: np.ndarray
    y: np.ndarray
    sigma: np.ndarray | None = None

    @property
    def weights(self) -> np.ndarray:
        if self.sigma is None:
            return np.ones_like(self.y)
        w = 1 / self.sigma**2
        return w / w.mean()


def make_series(points: list[tuple[float, float, float | None]], since: float | None = None, until: float | None = None) -> Series:
    rows = sorted((t, y, s) for t, y, s in points if (since is None or t >= since) and (until is None or t <= until))
    t = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)
    given = [r[2] for r in rows if r[2] is not None]
    sigma = None
    if given:
        fill = float(np.median(given))
        sigma = np.array([r[2] if r[2] is not None else fill for r in rows], dtype=float)
    return Series(t, y, sigma)


def _spacing(t: np.ndarray) -> float:
    gaps = np.diff(np.unique(t))
    return float(np.median(gaps)) if len(gaps) else 0.0


def _trend(tau: np.ndarray, kind: str) -> np.ndarray:
    columns = [np.ones_like(tau)]
    if kind in ("linear", "quadratic"):
        columns.append(tau)
    if kind == "quadratic":
        columns.append(tau**2)
    return np.column_stack(columns)


def _waves(t: np.ndarray, periods, harmonics: int) -> np.ndarray:
    columns = []
    for period in periods:
        for k in range(1, harmonics + 1):
            angle = TAU * k * t / period
            columns += [np.cos(angle), np.sin(angle)]
    return np.column_stack(columns) if columns else np.empty((len(t), 0))


def _wls(X: np.ndarray, y: np.ndarray, w: np.ndarray):
    root = np.sqrt(w)
    beta = np.linalg.lstsq(X * root[:, None], y * root, rcond=None)[0]
    resid = y - X @ beta
    return beta, resid, float(np.sum(w * resid**2))


def _lag1(values: np.ndarray) -> float:
    if len(values) < 3 or np.std(values) == 0:
        return 0.0
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def _anchor(resid: np.ndarray, spacing: float) -> tuple[float, float]:
    """Last residual and its per-year AR(1) persistence.

    Forecasts start from the latest observation and decay toward the fitted curve
    at the residuals' own persistence instead of jumping onto the curve.
    """
    rho = _lag1(resid)
    if not 0 < rho < 1 or spacing <= 0:
        return float(resid[-1]), 0.0
    return float(resid[-1]), rho ** (1 / spacing)


def _decay(per_year: float, dt) -> np.ndarray:
    return np.power(per_year, np.maximum(dt, 0)) if per_year > 0 else (np.asarray(dt) <= 0).astype(float)


def _psd_sqrt(cov: np.ndarray) -> np.ndarray:
    values, vectors = np.linalg.eigh((cov + cov.T) / 2)
    return vectors * np.sqrt(np.clip(values, 0, None))


def periodogram(t: np.ndarray, Y: np.ndarray, w: np.ndarray, base: np.ndarray, periods: np.ndarray, chunk: int = 128) -> np.ndarray:
    """Share of the base model's weighted residual variance removed by one sinusoid per period.

    Y may hold several series as columns (for surrogates); returns (len(periods), k).
    This is the generalized (floating-mean, trend-aware) Lomb-Scargle statistic.
    """
    Y = Y.reshape(len(t), -1)
    Yw = Y * w[:, None]
    d = base.shape[1]
    Bw = base * w[:, None]
    G0 = base.T @ Bw
    B0 = base.T @ Yw
    beta0 = np.linalg.lstsq(G0, B0, rcond=None)[0]
    yy = np.sum(Y * Yw, axis=0)
    sse0 = yy - np.sum(beta0 * B0, axis=0)
    out = np.zeros((len(periods), Y.shape[1]))
    eye = np.eye(d + 2)
    for start in range(0, len(periods), chunk):
        p = periods[start:start + chunk]
        angle = TAU * np.outer(1 / p, t)
        C, S = np.cos(angle), np.sin(angle)
        G = np.empty((len(p), d + 2, d + 2))
        G[:, :d, :d] = G0
        BC, BS = C @ Bw, S @ Bw
        G[:, :d, d], G[:, d, :d] = BC, BC
        G[:, :d, d + 1], G[:, d + 1, :d] = BS, BS
        G[:, d, d] = (C * C) @ w
        G[:, d + 1, d + 1] = (S * S) @ w
        G[:, d, d + 1] = G[:, d + 1, d] = (C * S) @ w
        G += (1e-10 * np.trace(G, axis1=1, axis2=2) / (d + 2))[:, None, None] * eye
        B = np.empty((len(p), d + 2, Y.shape[1]))
        B[:, :d, :] = B0
        B[:, d, :] = C @ Yw
        B[:, d + 1, :] = S @ Yw
        beta = np.linalg.solve(G, B)
        sse = yy - np.sum(beta * B, axis=1)
        out[start:start + len(p)] = np.where(sse0 > 0, (sse0 - sse) / np.where(sse0 > 0, sse0, 1), 0)
    return np.clip(out, 0, 1)


def period_grid(span: float, low: float, high: float, max_points: int = 1500) -> np.ndarray:
    count = int(np.clip(5 * span * (1 / low - 1 / high), 64, max_points))
    return 1 / np.linspace(1 / high, 1 / low, count)  # descending periods, uniform in frequency


def _golden(f, lo: float, hi: float, iterations: int = 40) -> float:
    ratio = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = f(d)
    return (a + b) / 2


def red_noise(t: np.ndarray, resid: np.ndarray, count: int, rng: np.random.Generator) -> np.ndarray:
    """AR(1) surrogates on the actual (possibly irregular) sampling times.

    The lag-1 autocorrelation includes any real cycle, which makes the null redder
    and the test conservative.
    """
    rho = _lag1(resid)
    gaps = np.diff(t)
    mean_gap = float(np.mean(gaps)) if len(gaps) else 1.0
    memory = -mean_gap / math.log(rho) if 0 < rho < 0.999 else (0.0 if rho <= 0 else 1e9)
    out = np.empty((len(t), count))
    out[0] = rng.standard_normal(count)
    for i, gap in enumerate(gaps, start=1):
        a = math.exp(-gap / memory) if memory > 0 else 0.0
        out[i] = a * out[i - 1] + math.sqrt(max(1 - a * a, 0)) * rng.standard_normal(count)
    scale = float(np.std(resid)) or 1.0
    return out / np.std(out, axis=0, keepdims=True).clip(1e-12) * scale


def turning_points(t: np.ndarray, y: np.ndarray, prominence: float = 0.05) -> list[dict]:
    if len(y) < 3:
        return []
    slope = np.sign(np.diff(y))
    for i in range(1, len(slope)):
        if slope[i] == 0:
            slope[i] = slope[i - 1]
    found = []
    for i in np.nonzero(slope[:-1] * slope[1:] < 0)[0]:
        j = i + 1
        kind = "peak" if slope[i] > 0 else "trough"
        y0, y1, y2 = y[j - 1], y[j], y[j + 1]
        denom = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denom if denom else 0.0
        shift = float(np.clip(shift, -1, 1))
        when = t[j] + shift * (t[j + 1] - t[j - 1]) / 2
        found.append({"type": kind, "t": float(when), "value": float(y1 - 0.25 * (y0 - y2) * shift)})
    threshold = prominence * (float(np.max(y) - np.min(y)) or 1.0)
    kept: list[dict] = []
    for point in found:
        if kept and abs(point["value"] - kept[-1]["value"]) < threshold:
            kept.pop()  # a small wiggle cancels the preceding extremum
            continue
        if kept and kept[-1]["type"] == point["type"]:
            if (point["value"] > kept[-1]["value"]) == (point["type"] == "peak"):
                kept[-1] = point
            continue
        kept.append(point)
    return kept


def _timing(points: list[dict], t: np.ndarray, curves: np.ndarray, window: float) -> list[dict]:
    """Attach 10-90% timing windows and draw support to point-estimate turning points."""
    draws = [turning_points(t, curve) for curve in curves]
    out = []
    for point in points:
        times = []
        for found in draws:
            near = [p["t"] for p in found if p["type"] == point["type"] and abs(p["t"] - point["t"]) <= window]
            if near:
                times.append(min(near, key=lambda x: abs(x - point["t"])))
        entry = {"type": point["type"], "t": _r(point["t"]), "date": to_date(point["t"]), "value": _r(point["value"]), "support": _r(len(times) / max(len(curves), 1), 3)}
        if len(times) >= 10:
            low, high = np.percentile(times, [10, 90])
            entry["window"] = [to_date(low), to_date(high)]
        out.append(entry)
    return out


def _backtest(predict, t: np.ndarray, y: np.ndarray, fraction: float, minimum: int) -> dict:
    if fraction <= 0:
        return {"status": "disabled"}
    cutoff = t[0] + (1 - fraction) * (t[-1] - t[0])
    train, test = t <= cutoff, t > cutoff
    if train.sum() < minimum or test.sum() < 3:
        return {"status": "skipped", "reason": f"needs at least {minimum} training and 3 holdout points"}
    try:
        forecast, trend_only = predict(train, t[test])
    except InsufficientData as exc:
        return {"status": "skipped", "reason": str(exc)}
    actual = y[test]

    def rmse(values):
        return float(np.sqrt(np.mean((actual - values) ** 2)))

    model, persistence, trend = rmse(forecast), rmse(np.full(test.sum(), y[train][-1])), rmse(trend_only)
    return {
        "status": "completed",
        "cutoff": to_date(cutoff),
        "holdout_points": int(test.sum()),
        "rmse": _r(model),
        "rmse_persistence": _r(persistence),
        "rmse_trend_only": _r(trend),
        "skill_vs_persistence": _r(1 - model / persistence) if persistence else None,
        "skill_vs_trend": _r(1 - model / trend) if trend else None,
    }


# ----------------------------------------------------------------------------- harmonic


def _bounds(spec: dict, spacing: float, span: float) -> tuple[float, float]:
    low = spec.get("period_min_years") or max(2.5 * spacing, 1e-6)
    high = spec.get("period_max_years") or span
    if low >= high:
        raise InsufficientData(f"Period search range [{low:.3g}, {high:.3g}] years is empty for this span")
    return low, high


def _harmonic_core(t, y, w, spec: dict, low: float, high: float, frame: tuple[float, float]):
    tau = (t - frame[0]) / frame[1]
    base = _trend(tau, spec["trend"])
    K, count = spec["harmonics"], spec["cycles"]
    needed = max(8, base.shape[1] + 2 * K * count + 3)
    if len(t) < needed:
        raise InsufficientData(f"Harmonic model needs at least {needed} observations; have {len(t)}")

    def sse(periods, k=K):
        return _wls(np.hstack([base, _waves(t, periods, k)]), y, w)[2]

    power = None
    if spec.get("period_years"):
        periods = [float(spec["period_years"])]
    else:
        grid = period_grid(t[-1] - t[0], low, high)
        periods: list[float] = []
        for _ in range(count):
            current = np.hstack([base, _waves(t, periods, K)])
            scan = periodogram(t, y, w, current, grid)[:, 0]
            if power is None:
                power = scan
            for p in periods:
                scan = np.where(np.abs(grid / p - 1) < 0.1, -1, scan)
            i = int(np.argmax(scan))
            lo, hi = grid[min(i + 1, len(grid) - 1)], grid[max(i - 1, 0)]
            fixed = list(periods)
            periods.append(_golden(lambda P, fixed=fixed: sse([*fixed, P], 1), min(lo, hi), max(lo, hi)))
        for _ in range(2 if count > 1 or K > 1 else 0):
            for j in range(count):
                others = periods[:j] + periods[j + 1:]
                lo, hi = max(low, periods[j] * 0.97), min(high, periods[j] * 1.03)
                if lo < hi:
                    periods[j] = _golden(lambda P, others=others, j=j: sse([*others[:j], P, *others[j:]]), lo, hi, 30)
    X = np.hstack([base, _waves(t, periods, K)])
    beta, resid, total = _wls(X, y, w)
    return periods, base, X, beta, resid, total, power, sse


def harmonic_value(params: dict, t: np.ndarray, *, cycle_only: bool = False) -> np.ndarray:
    tau = (t - params["t0"]) / params["scale"]
    base = _trend(tau, params["trend"])
    beta = np.array(params["coefficients"], dtype=float)
    waves = _waves(t, params["periods"], params["harmonics"])
    d = base.shape[1]
    value = waves @ beta[d:]
    return value if cycle_only else base @ beta[:d] + value


def fit_harmonic(series: Series, spec: dict, seed: int) -> dict:
    t, y, w = series.t, series.y, series.weights
    span = float(t[-1] - t[0]) if len(t) else 0.0
    if span <= 0:
        raise InsufficientData("Need observations at two or more distinct dates")
    spacing = _spacing(t)
    low, high = _bounds(spec, spacing, span)
    frame = (float(np.mean(t)), max(span / 2, 1e-9))
    periods, base, X, beta, resid, total, power, sse_of = _harmonic_core(t, y, w, spec, low, high, frame)
    n, q = len(t), X.shape[1]
    searched = not spec.get("period_years")
    dof = max(n - q - (len(periods) if searched else 0), 1)
    sigma2 = total / dof
    rho = _lag1(resid)
    inflation = min((1 + max(rho, 0)) / (1 - min(max(rho, 0), 0.95)), 20.0)
    mean_w = np.sum(w * y) / np.sum(w)
    sst = float(np.sum(w * (y - mean_w) ** 2)) or 1.0
    trend_sse = _wls(base, y, w)[2]
    K = spec["harmonics"]
    d = base.shape[1]

    errors = []
    for j, p in enumerate(periods):
        if not searched:
            errors.append(0.0)
            continue
        h = p * 1e-3
        others = periods[:j] + periods[j + 1:]

        def at(P, others=others, j=j):
            return sse_of([*others[:j], P, *others[j:]])

        curvature = (at(p + h) - 2 * at(p) + at(p - h)) / h**2
        errors.append(math.sqrt(2 * sigma2 * inflation / curvature) if curvature > 0 else float("nan"))

    params = {"t0": frame[0], "scale": frame[1], "trend": spec["trend"], "periods": [float(p) for p in periods], "harmonics": K, "coefficients": beta.tolist()}
    components = []
    t_end = float(t[-1])
    for j, p in enumerate(periods):
        a, b = beta[d + 2 * K * j], beta[d + 2 * K * j + 1]
        delta = math.atan2(b, a)
        single = {**params, "periods": [p], "coefficients": [*([0.0] * d), *beta[d + 2 * K * j: d + 2 * K * (j + 1)]]}
        one_cycle = harmonic_value(single, np.linspace(0, p, 257), cycle_only=True)
        phi = (TAU * t_end / p - delta) % TAU
        components.append({
            "period_years": _r(p),
            "period_se_years": _r(errors[j]),
            "amplitude": _r((one_cycle.max() - one_cycle.min()) / 2),
            "phase_offset": _r(delta),
            "phase_at_end": _r(phi),
            "phase_label_at_end": phase_label(phi),
            "cycles_observed": _r(span / p, 3),
        })
    params["components"] = [{"period_years": c["period_years"], "phase_offset": c["phase_offset"]} for c in components]

    rng = np.random.default_rng(seed)
    horizon = float(spec["horizon_years"])
    step = max(min(periods) / 48, horizon / 1500)
    tp = np.linspace(t_end, t_end + horizon, int(horizon / step) + 1)
    tc = np.linspace(t[0], t_end, int(min(max(span / step, 64), 1500)) + 1)
    sd = math.sqrt(sigma2)
    last_resid, persistence = _anchor(resid, spacing)
    params["anchor"] = {"t_end": t_end, "residual": last_resid, "persistence_per_year": persistence}
    decay = _decay(persistence, tp - t_end)
    draws_mean = np.empty((DRAWS, len(tp)))
    for i in range(DRAWS):
        drawn = [float(np.clip(p + (e if math.isfinite(e) else 0) * rng.standard_normal(), low * 0.5, high * 2)) for p, e in zip(periods, errors)]
        Xd = np.hstack([base, _waves(t, drawn, K)])
        bd = _wls(Xd, y, w)[0]
        covd = sigma2 * inflation * np.linalg.pinv(Xd.T @ (Xd * w[:, None]))
        sample = bd + _psd_sqrt(covd) @ rng.standard_normal(len(bd))
        curve = harmonic_value({**params, "periods": drawn, "coefficients": sample}, tp)
        draws_mean[i] = curve + (y[-1] - curve[0]) * decay
    predictive = draws_mean + sd * np.sqrt(np.clip(1 - decay**2, 0, 1)) * rng.standard_normal(draws_mean.shape)
    point = harmonic_value(params, tp) + last_resid * decay
    lower, upper = np.percentile(predictive, [10, 90], axis=0)
    fitted = harmonic_value(params, tc)
    window = min(periods) / 4

    significance: dict = {"status": "disabled"}
    if spec["surrogates"] > 0:
        resid0 = _wls(base, y, w)[1]
        if searched:
            grid = period_grid(span, low, high, max_points=300)
            count = int(min(spec["surrogates"], max(20, 1.5e8 // (len(grid) * n))))
            observed = float(periodogram(t, y, w, base, grid).max())
            null = periodogram(t, red_noise(t, resid0, count, rng), w, base, grid).max(axis=0)
            method = "max generalized periodogram power over the searched band vs AR(1) red-noise surrogates"
        else:
            grid = np.array([periods[0]])
            count = int(spec["surrogates"])
            observed = float(periodogram(t, y, w, base, grid)[0, 0])
            null = periodogram(t, red_noise(t, resid0, count, rng), w, base, grid)[0]
            method = "power at the pre-specified period vs AR(1) red-noise surrogates"
        significance = {
            "status": "completed",
            "method": method,
            "statistic": _r(observed),
            "surrogates": count,
            "p_value": _r((1 + int(np.sum(null >= observed))) / (1 + count), 4),
            "null_95th_percentile": _r(np.percentile(null, 95)),
        }

    def predict(train, future):
        sub = Series(t[train], y[train], None if series.sigma is None else series.sigma[train])
        tt = sub.t
        sub_frame = (float(np.mean(tt)), max(float(tt[-1] - tt[0]) / 2, 1e-9))
        try:
            sub_low, sub_high = _bounds(spec, _spacing(tt), float(tt[-1] - tt[0]))
        except InsufficientData:
            sub_low, sub_high = low, high
        result = _harmonic_core(tt, sub.y, sub.weights, spec, sub_low, max(sub_high, sub_low * 1.01), sub_frame)
        sub_params = {"t0": sub_frame[0], "scale": sub_frame[1], "trend": spec["trend"], "periods": result[0], "harmonics": K, "coefficients": result[3].tolist()}
        gap = _spacing(tt)
        cycle_resid, cycle_keep = _anchor(result[4], gap)
        base_beta, base_resid, _ = _wls(result[1], sub.y, sub.weights)
        trend_resid, trend_keep = _anchor(base_resid, gap)
        trend_future = _trend((future - sub_frame[0]) / sub_frame[1], spec["trend"]) @ base_beta
        # Both forecasts start from the last training value; the cycle must add skill beyond AR(1) persistence.
        return harmonic_value(sub_params, future) + cycle_resid * _decay(cycle_keep, future - tt[-1]), trend_future + trend_resid * _decay(trend_keep, future - tt[-1])

    backtest = _backtest(predict, t, y, spec["holdout_fraction"], max(8, q + 3))
    effective_n = n * (1 - max(rho, 0)) / (1 + max(rho, 0))
    warnings = []
    if min(c["cycles_observed"] for c in components) < 2:
        warnings.append("Fewer than two full cycles observed: period and phase are under-identified; treat as a hypothesis.")
    if max(periods) > span:
        warnings.append("Fitted period exceeds the observed span; it cannot be distinguished from trend curvature.")
    if significance.get("p_value") is not None and significance["p_value"] >= 0.05:
        warnings.append("Cycle is not distinguishable from autocorrelated red noise at the 5% level (Slutsky-Yule risk).")
    if backtest.get("skill_vs_trend") is not None and backtest["skill_vs_trend"] <= 0:
        warnings.append("Out-of-sample holdout did not beat a trend-only baseline.")
    if rho > 0.5:
        warnings.append("Residuals are strongly autocorrelated; compare an oscillator fit and treat intervals as optimistic.")
    if series.sigma is None:
        warnings.append("No per-point uncertainty supplied; all observations weigh equally.")
    verdict = _verdict(components, significance, backtest)

    return {
        "params": params,
        "components": components,
        "diagnostics": {
            "r2": _r(1 - total / sst, 4),
            "r2_trend_only": _r(1 - trend_sse / sst, 4),
            "residual_sd": _r(sd),
            "residual_autocorrelation": _r(rho, 3),
            "effective_n": _r(effective_n, 3),
            "period_search_years": [_r(low), _r(high)] if searched else None,
            "periodogram": {"periods": _r(period_grid(span, low, high, 200)), "power": _r(periodogram(t, y, w, base, period_grid(span, low, high, 200))[:, 0], 4)} if searched else None,
            "significance": significance,
            "backtest": backtest,
        },
        "turning_points": {
            "historical": [{"type": p["type"], "t": _r(p["t"]), "date": to_date(p["t"]), "value": _r(p["value"])} for p in turning_points(tc, fitted)],
            "upcoming": _timing(turning_points(tp, point)[:6], tp, draws_mean, window),
        },
        "projection": {"t": _r(tp), "mean": _r(point), "lower": _r(lower), "upper": _r(upper), "interval": "80% predictive, assuming the fitted cycle persists"},
        "curve": {"t": _r(tc), "y": _r(fitted), "label": "fitted trend + cycle"},
        "warnings": warnings,
        "verdict": verdict,
    }


def _verdict(components, significance, backtest) -> str:
    if min(c["cycles_observed"] for c in components) < 2:
        return "under-identified"
    p = significance.get("p_value")
    skill = backtest.get("skill_vs_trend")
    if p is not None and p < 0.05 and (skill is None or skill > 0):
        return "supported"
    return "weak"


# ----------------------------------------------------------------------------- oscillator


def _ar(x: np.ndarray, order: int):
    lags = np.column_stack([x[order - j - 1: len(x) - j - 1] for j in range(order)])
    target = x[order:]
    phi = np.linalg.lstsq(lags, target, rcond=None)[0]
    resid = target - lags @ phi
    sse = float(resid @ resid)
    sigma2 = sse / max(len(target) - order, 1)
    return phi, sigma2, sigma2 * np.linalg.pinv(lags.T @ lags), resid


def _impulse(phi: np.ndarray, steps: int) -> np.ndarray:
    psi = np.zeros(steps + 1)
    psi[0] = 1.0
    for j in range(1, steps + 1):
        psi[j] = sum(phi[i] * psi[j - i - 1] for i in range(min(len(phi), j)))
    return psi


def _dominant(phi: np.ndarray):
    roots = np.roots(np.r_[1.0, -phi]) if len(phi) else np.array([])
    complex_roots = [r for r in roots if r.imag > 1e-9]
    return roots, (max(complex_roots, key=abs) if complex_roots else None)


def _regular(series: Series, step: float):
    unique, inverse = np.unique(series.t, return_inverse=True)
    values = np.bincount(inverse, weights=series.y) / np.bincount(inverse)
    grid = np.arange(unique[0], unique[-1] + step / 2, step)
    nearest = np.min(np.abs(grid[:, None] - unique[None, :]), axis=1) if len(unique) < 20000 else np.zeros(len(grid))
    return grid, np.interp(grid, unique, values), float(np.mean(nearest > step / 2))


def oscillator_phase(params: dict, t: float) -> float | None:
    if params.get("phase_at_end") is None:
        return None
    return (params["phase_at_end"] + params["phase_rate"] * (t - params["t_end"])) % TAU


def fit_oscillator(series: Series, spec: dict, seed: int) -> dict:
    if len(series.t) < 2 or series.t[-1] <= series.t[0]:
        raise InsufficientData("Need observations at two or more distinct dates")
    step = float(spec.get("step_years") or _spacing(series.t))
    order = int(spec["order"])
    grid, values, interpolated = _regular(series, step)
    needed = max(16, 4 * order + 4)
    if len(grid) < needed:
        raise InsufficientData(f"Oscillator model needs at least {needed} regular steps; have {len(grid)}")
    span = float(grid[-1] - grid[0])
    frame = (float(np.mean(grid)), max(span / 2, 1e-9))
    base = _trend((grid - frame[0]) / frame[1], spec["trend"])
    trend_beta = np.linalg.lstsq(base, values, rcond=None)[0]
    x = values - base @ trend_beta
    phi, sigma2, cov, resid = _ar(x, order)
    roots, dominant = _dominant(phi)
    stationary = bool(np.all(np.abs(roots) < 1)) if len(roots) else True
    rows = len(x) - order
    sse_p = float(resid @ resid)
    sse_1 = float(np.sum((x[order:] - _ar_fit_rows(x, order)) ** 2))
    aic = lambda sse, k: rows * math.log(max(sse, 1e-300) / rows) + 2 * k  # noqa: E731
    delta_aic = aic(sse_1, 1) - aic(sse_p, order)

    horizon = float(spec["horizon_years"])
    steps = max(int(math.ceil(horizon / step)), 1)
    psi = _impulse(phi, steps)
    dynamics: dict = {
        "coefficients": _r(phi),
        "roots": [{"real": _r(r.real), "imag": _r(r.imag), "modulus": _r(abs(r))} for r in roots],
        "stationary": stationary,
        "persistence": _r(float(np.sum(phi)), 4),
        "innovation_sd": _r(math.sqrt(sigma2)),
        "delta_aic_vs_ar1": _r(delta_aic, 4) if order > 1 else None,
        "impulse_response": {"years": _r(np.arange(steps + 1) * step), "response": _r(psi)},
    }
    after = psi[1:]
    dynamics["overshoot"] = _r(max(-float(after.min()), 0.0) if len(after) else 0.0, 4)
    crossing = np.nonzero(psi < 0)[0]
    dynamics["first_zero_crossing_years"] = _r(crossing[0] * step) if len(crossing) else None

    params = {"t0": frame[0], "scale": frame[1], "trend": spec["trend"], "trend_coefficients": trend_beta.tolist(), "step": step, "order": order, "phi": phi.tolist(), "t_end": float(grid[-1]), "phase_at_end": None, "phase_rate": None}
    rng = np.random.default_rng(seed)
    p_oscillatory = None
    if dominant is not None:
        r, theta = abs(dominant), abs(math.atan2(dominant.imag, dominant.real))
        period = TAU / theta * step
        log_r = math.log(r) if r > 0 else -50.0
        dynamics.update({
            "oscillatory": True,
            "period_years": _r(period),
            "damping_per_year": _r(r ** (1 / step)),
            "half_life_years": _r(math.log(0.5) / log_r * step) if r < 1 else None,
            "damping_ratio": _r(-log_r / math.hypot(log_r, theta), 4),
            "cycles_observed": _r(span / period, 3),
        })
        if order == 2:
            mu = 1 / dominant
            real = x[-1]
            imag = (real * mu.real - x[-2]) / mu.imag if mu.imag else 0.0
            phase = math.atan2(imag, real) % TAU
            params.update(phase_at_end=phase, phase_rate=theta / step)
            dynamics.update(phase_at_end=_r(phase), phase_label_at_end=phase_label(phase))
    else:
        dynamics.update({"oscillatory": False, "period_years": None, "half_life_years": _r(math.log(0.5) / math.log(abs(roots).max()) * step) if len(roots) and 0 < abs(roots).max() < 1 else None})
    if order >= 2:
        samples = phi + (_psd_sqrt(cov) @ rng.standard_normal((order, 2000))).T
        p_oscillatory = float(np.mean([_dominant(s)[1] is not None for s in samples[:400]]))
        dynamics["p_oscillatory"] = _r(p_oscillatory, 3)

    tp = grid[-1] + step * np.arange(steps + 1)
    trend_future = _trend((tp - frame[0]) / frame[1], spec["trend"]) @ trend_beta
    point = trend_future + _forecast(x, phi, steps)
    draws = phi + (_psd_sqrt(cov) @ rng.standard_normal((order, DRAWS))).T
    keep = np.array([np.all(np.abs(np.roots(np.r_[1.0, -d])) < 1) for d in draws])
    if keep.sum() >= DRAWS // 4:
        draws = draws[keep]
    mean_paths = np.array([trend_future + _forecast(x, d, steps) for d in draws])
    noisy = _simulate(x, draws, steps, math.sqrt(sigma2), rng) + trend_future
    lower, upper = np.percentile(noisy, [10, 90], axis=0)
    period_ref = (dynamics.get("period_years") or horizon * 2)

    def predict(train, future):
        sub_t = series.t[train]
        sub = Series(sub_t, series.y[train])
        g, v, _ = _regular(sub, step)
        if len(g) < needed:
            raise InsufficientData("Training window too short for the oscillator backtest")
        f = (float(np.mean(g)), max(float(g[-1] - g[0]) / 2, 1e-9))
        b = _trend((g - f[0]) / f[1], spec["trend"])
        tb = np.linalg.lstsq(b, v, rcond=None)[0]
        xx = v - b @ tb
        ph = _ar(xx, order)[0]
        h = max(int(math.ceil((future[-1] - g[-1]) / step)), 1)
        path_t = g[-1] + step * np.arange(h + 1)
        tf = _trend((path_t - f[0]) / f[1], spec["trend"]) @ tb
        path = tf + _forecast(xx, ph, h)
        resid_end, keep = _anchor(xx, step)
        trend_path = tf + resid_end * _decay(keep, path_t - g[-1])
        return np.interp(future, path_t, path), np.interp(future, path_t, trend_path)

    backtest = _backtest(predict, series.t, series.y, spec["holdout_fraction"], needed)
    warnings = []
    if interpolated > 0.25:
        warnings.append(f"{interpolated:.0%} of regular steps were interpolated between observations; interpolation smooths the series and can create spurious persistence.")
    if not stationary:
        warnings.append("Estimated dynamics are non-stationary (unit or explosive root); projections are unreliable.")
    if dominant is None:
        warnings.append("No complex roots: the series shows persistence but no intrinsic oscillation.")
    elif dynamics.get("cycles_observed", 0) < 2:
        warnings.append("Fewer than two implied cycles observed: the oscillation period is under-identified.")
    if backtest.get("skill_vs_trend") is not None and backtest["skill_vs_trend"] <= 0:
        warnings.append("Out-of-sample holdout did not beat a trend-only baseline.")
    if dominant is None:
        verdict = "not-oscillatory"
    elif dynamics.get("cycles_observed", 0) < 2:
        verdict = "under-identified"
    elif (p_oscillatory or 0) >= 0.9 and (delta_aic > 2 or order == 1) and stationary:
        verdict = "supported"
    else:
        verdict = "weak"
    return {
        "params": params,
        "dynamics": dynamics,
        "diagnostics": {
            "r2_one_step": _r(1 - sse_p / float(np.sum((x[order:] - x[order:].mean()) ** 2) or 1), 4),
            "interpolated_fraction": _r(interpolated, 3),
            "regular_steps": len(grid),
            "step_years": _r(step),
            "significance": {"status": "completed", "method": "share of parameter draws with complex dominant roots; AIC gain over AR(1)", "p_oscillatory": dynamics.get("p_oscillatory"), "delta_aic_vs_ar1": dynamics.get("delta_aic_vs_ar1")},
            "backtest": backtest,
        },
        "turning_points": {"historical": [], "upcoming": _timing(turning_points(tp, point)[:6], tp, mean_paths, period_ref / 4)},
        "projection": {"t": _r(tp), "mean": _r(point), "lower": _r(lower), "upper": _r(upper), "interval": "80% predictive, including shocks and coefficient uncertainty"},
        "curve": {"t": _r(grid), "y": _r(base @ trend_beta), "label": "equilibrium trend"},
        "warnings": warnings,
        "verdict": verdict,
    }


def _ar_fit_rows(x: np.ndarray, order: int) -> np.ndarray:
    """AR(1) fitted values over the same rows as an AR(order) fit, for AIC comparison."""
    lagged, target = x[order - 1:-1], x[order:]
    coef = float(lagged @ target / (lagged @ lagged)) if lagged @ lagged else 0.0
    return coef * lagged


def _forecast(x: np.ndarray, phi: np.ndarray, steps: int) -> np.ndarray:
    order = len(phi)
    state = list(x[-order:][::-1])  # most recent first
    out = [float(x[-1])]
    for _ in range(steps):
        value = float(np.dot(phi, state[:order]))
        out.append(value)
        state = [value, *state[:-1]]
    return np.array(out)


def _simulate(x: np.ndarray, draws: np.ndarray, steps: int, sd: float, rng) -> np.ndarray:
    order = draws.shape[1]
    state = np.tile(x[-order:][::-1], (len(draws), 1))
    out = np.empty((len(draws), steps + 1))
    out[:, 0] = x[-1]
    for h in range(1, steps + 1):
        value = np.sum(draws * state, axis=1) + sd * rng.standard_normal(len(draws))
        out[:, h] = value
        state = np.column_stack([value, state[:, :-1]])
    return out


# ----------------------------------------------------------------------------- discovery


def residual_spectrum(t: np.ndarray, resid: np.ndarray, w: np.ndarray, existing: list[float], seed: int, surrogates: int = 200, low: float | None = None, high: float | None = None) -> dict:
    """Search residuals for further periodicity: candidate hidden cycles, not findings."""
    span = float(t[-1] - t[0])
    low = low or 2.5 * _spacing(t)
    high = high or span
    if len(t) < 12 or low >= high:
        raise InsufficientData("Residual search needs at least 12 observations and a non-empty period band")
    base = np.ones((len(t), 1))
    grid = period_grid(span, low, high, 600)
    power = periodogram(t, resid, w, base, grid)[:, 0]
    rng = np.random.default_rng(seed)
    count = int(min(surrogates, max(20, 1.5e8 // (len(grid) * len(t)))))
    null = periodogram(t, red_noise(t, resid, count, rng), w, base, grid).max(axis=0) if count else np.array([])
    peaks = [i for i in range(1, len(power) - 1) if power[i] >= power[i - 1] and power[i] >= power[i + 1]]
    peaks = sorted(peaks, key=lambda i: -power[i])[:5]
    candidates = []
    for i in peaks:
        period = float(grid[i])
        relation = None
        for p in existing:
            for k in (1, 2, 3, 4):
                if abs(period / (p / k) - 1) < 0.07:
                    relation = "same period as fitted cycle: amplitude or phase drift" if k == 1 else f"harmonic {k} of the {p:.3g}-year cycle: consider more harmonics"
                    break
            if relation:
                break
        candidates.append({
            "period_years": _r(period),
            "power": _r(power[i], 4),
            "p_value": _r((1 + int(np.sum(null >= power[i]))) / (1 + len(null)), 4) if len(null) else None,
            "cycles_observed": _r(span / period, 3),
            "relation": relation,
        })
    return {"band_years": [_r(low), _r(high)], "surrogates": count, "candidates": candidates, "method": "family-wise: each peak vs the maximum residual power of AR(1) red-noise surrogates"}
