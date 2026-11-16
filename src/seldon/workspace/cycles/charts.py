"""Self-contained SVG charts for cycle factors and composites (no JS, no network).

Observed data is drawn in neutral ink and the model in one hue; separate measures
(alignment, shock response) get their own panels instead of a second y-axis.
Marks carry <title> tooltips. Colors are CSS custom properties with a dark variant.
"""

from __future__ import annotations

import math
from datetime import date
from html import escape

from .fitting import decimal_year

WIDTH = 960
LEFT, RIGHT = 64, 24
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
STYLE = """
.viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#8a8984; --grid:#e7e6e2; --data:#52514e; %s }
@media (prefers-color-scheme: dark) { .viz { --surface:#1a1a19; --ink:#f0efec; --ink-2:#c3c2b7; --muted:#8f8e88; --grid:#2f2f2d; --data:#c3c2b7; %s } }
.viz text { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; fill: var(--ink-2); font-size: 12px; }
.viz .title { fill: var(--ink); font-size: 16px; font-weight: 600; }
.viz .sub { font-size: 12px; }
.viz .note { fill: var(--muted); font-size: 11px; }
.viz .grid { stroke: var(--grid); stroke-width: 1; }
.viz .axis { stroke: var(--muted); stroke-width: 1; }
.viz .marker { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; }
""" % (
    " ".join(f"--s{i + 1}:{c};" for i, c in enumerate(SERIES)),
    " ".join(f"--s{i + 1}:{c};" for i, c in enumerate(SERIES_DARK)),
)


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    if not (math.isfinite(low) and math.isfinite(high)) or high <= low:
        return [low]
    raw = (high - low) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.ceil(low / step) * step
    return [start + i * step for i in range(int((high - start) / step) + 1)]


def _fmt(value: float) -> str:
    return f"{value:.4g}" if abs(value) < 1e5 else f"{value:.3g}"


class Panel:
    def __init__(self, top: float, height: float, x0: float, x1: float, y0: float, y1: float):
        pad = (y1 - y0) * 0.06 or 1.0
        self.top, self.height = top, height
        self.x0, self.x1 = x0, x1
        self.y0, self.y1 = y0 - pad, y1 + pad

    def x(self, t: float) -> float:
        return LEFT + (t - self.x0) / (self.x1 - self.x0 or 1) * (WIDTH - LEFT - RIGHT)

    def y(self, v: float) -> float:
        return self.top + self.height - (v - self.y0) / (self.y1 - self.y0 or 1) * self.height

    def clip(self, key: str) -> str:
        return f'<clipPath id="{key}"><rect x="{LEFT}" y="{self.top}" width="{WIDTH - LEFT - RIGHT}" height="{self.height}"/></clipPath>'

    def line(self, ts, vs, *, stroke: str, width: float = 2, dash: str | None = None, opacity: float = 1) -> str:
        pieces, current = [], []
        for t, v in zip(ts, vs):
            if v is None or not math.isfinite(v):
                if len(current) > 1:
                    pieces.append(current)
                current = []
                continue
            current.append(f"{self.x(t):.1f},{self.y(v):.1f}")
        if len(current) > 1:
            pieces.append(current)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        return "".join(f'<polyline fill="none" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round" opacity="{opacity}"{dash_attr} points="{" ".join(p)}"/>' for p in pieces)

    def band(self, ts, lows, highs, *, fill: str, opacity: float = 0.16) -> str:
        rows = [(t, lo, hi) for t, lo, hi in zip(ts, lows, highs) if lo is not None and hi is not None and math.isfinite(lo) and math.isfinite(hi)]
        if len(rows) < 2:
            return ""
        upper = [f"{self.x(t):.1f},{self.y(hi):.1f}" for t, _, hi in rows]
        lower = [f"{self.x(t):.1f},{self.y(lo):.1f}" for t, lo, _ in reversed(rows)]
        return f'<polygon fill="{fill}" opacity="{opacity}" stroke="none" points="{" ".join(upper + lower)}"/>'

    def axes(self, *, units: str = "", years: bool = True) -> str:
        out = []
        for v in _ticks(self.y0, self.y1, 4):
            y = self.y(v)
            out.append(f'<line class="grid" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/><text x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
        bottom = self.top + self.height
        out.append(f'<line class="axis" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{bottom:.1f}" y2="{bottom:.1f}"/>')
        for t in _ticks(self.x0, self.x1, 8):
            x = self.x(t)
            label = str(int(round(t))) if years else _fmt(t)
            out.append(f'<line class="axis" x1="{x:.1f}" x2="{x:.1f}" y1="{bottom:.1f}" y2="{bottom + 4:.1f}"/><text x="{x:.1f}" y="{bottom + 18:.1f}" text-anchor="middle">{label}</text>')
        if units:
            out.append(f'<text x="{LEFT}" y="{self.top - 8:.1f}" class="note">{escape(units)}</text>')
        return "".join(out)

    def vline(self, t: float, label: str) -> str:
        if not self.x0 <= t <= self.x1:
            return ""
        x = self.x(t)
        return f'<line class="marker" x1="{x:.1f}" x2="{x:.1f}" y1="{self.top}" y2="{self.top + self.height}"/><text class="note" x="{x + 4:.1f}" y="{self.top + 12:.1f}">{escape(label)}</text>'


def _legend(items: list[tuple[str, str]], y: float) -> str:
    return _legend_rows(items, y)[0]


def _legend_rows(items: list[tuple[str, str]], y: float) -> tuple[str, float]:
    """Legend that wraps onto new rows; returns markup and the y below the last row."""
    out, x = [], LEFT
    for swatch, label in items:
        width = 34 + 7 * len(label)
        if x > LEFT and x + width > WIDTH - RIGHT:
            x, y = LEFT, y + 20
        out.append(f'<g transform="translate({x},{y})">{swatch}<text x="22" y="4">{escape(label)}</text></g>')
        x += width
    return "".join(out), y + 12


def _svg(height: float, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {WIDTH} {height:.0f}" width="{WIDTH}" height="{height:.0f}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title><style>{STYLE}</style>"
        f'<rect width="100%" height="100%" fill="var(--surface)"/>{body}</svg>'
    )


def _finite(values) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


def factor_chart(factor: dict, observations: list[dict], fit: dict | None, *, as_of: date | None = None) -> str:
    points = [(decimal_year(date.fromisoformat(o["date"])), o["value"], o["kind"], o) for o in observations if o["status"] == "active"]
    title = f"{factor['name']} ({factor['region']})"
    if not points and not fit:
        return _svg(120, f'<text class="title" x="{LEFT}" y="32">{escape(title)}</text><text class="sub" x="{LEFT}" y="56">No observations or fits recorded yet.</text>', title)
    ts = [p[0] for p in points]
    values = [p[1] for p in points]
    projection = (fit or {}).get("projection") or {}
    curve = (fit or {}).get("curve") or {}
    all_t = ts + projection.get("t", []) + curve.get("t", [])
    all_v = values + _finite(projection.get("lower", [])) + _finite(projection.get("upper", [])) + _finite(curve.get("y", []))
    oscillator = fit is not None and fit["model"] == "oscillator"
    top = 112
    main = Panel(top, 260, min(all_t), max(all_t), min(all_v), max(all_v))
    body = [f'<text class="title" x="{LEFT}" y="30">{escape(title)}</text>']
    if fit:
        diagnostics = fit.get("diagnostics", {})
        sig = diagnostics.get("significance") or {}
        p = sig.get("p_value", sig.get("p_oscillatory"))
        if fit["model"] == "harmonic":
            periods = ", ".join(f"{c['period_years']:.3g}" for c in fit["components"])
        else:
            periods = f"{fit['dynamics']['period_years']:.3g}" if fit["dynamics"].get("period_years") else None
        p_label = "red-noise p" if fit["model"] == "harmonic" else "P(oscillatory)"
        skill = (diagnostics.get("backtest") or {}).get("skill_vs_trend")
        period_text = f"period ≈ {periods} y" if periods else "no intrinsic period"
        skill_text = f"{skill:.2f}" if isinstance(skill, (int, float)) else "n/a"
        sub = f"{fit['model']} fit {fit['id'][:8]} · verdict: {fit['verdict']} · {period_text} · {p_label} = {p} · holdout skill vs trend = {skill_text}"
    else:
        sub = "No fit recorded for the preferred specification"
    body.append(f'<text class="sub" x="{LEFT}" y="52">{escape(sub)}</text>')
    present = {p[2] for p in points}
    legend = [
        item for kind, item in (
            ("measured", ('<circle cx="8" cy="0" r="4" fill="var(--data)" stroke="var(--surface)" stroke-width="1.5"/>', "Measured")),
            ("coded", ('<rect x="4" y="-4" width="8" height="8" transform="rotate(45 8 0)" fill="var(--data)"/>', "Coded")),
            ("assumption", ('<circle cx="8" cy="0" r="4" fill="none" stroke="var(--data)" stroke-width="1.5"/>', "Assumption")),
        ) if kind in present
    ]
    if fit:
        legend += [
            ('<line x1="0" x2="16" y1="0" y2="0" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="2 3"/>', "Equilibrium trend") if oscillator else ('<line x1="0" x2="16" y1="0" y2="0" stroke="var(--s1)" stroke-width="2"/>', "Fitted cycle + trend"),
            ('<line x1="0" x2="16" y1="0" y2="0" stroke="var(--s1)" stroke-width="2" stroke-dasharray="5 4"/>', "Projection"),
            ('<rect x="0" y="-6" width="16" height="12" fill="var(--s1)" opacity="0.16"/>', "80% band"),
        ]
    body.append(_legend(legend, 80))
    body.append(main.axes(units=factor["units"]))
    if factor.get("high_label"):
        body.append(f'<text class="note" x="{LEFT + 6}" y="{top + 12}">↑ {escape(factor["high_label"])}</text>')
    if factor.get("low_label"):
        body.append(f'<text class="note" x="{LEFT + 6}" y="{top + main.height - 6}">↓ {escape(factor["low_label"])}</text>')
    if fit:
        body.append(main.band(projection["t"], projection["lower"], projection["upper"], fill="var(--s1)"))
        body.append(main.line(curve.get("t", []), curve.get("y", []), stroke="var(--muted)" if oscillator else "var(--s1)", width=1.5 if oscillator else 2, dash="2 3" if oscillator else None))
        body.append(main.line(projection["t"], projection["mean"], stroke="var(--s1)", dash="5 4"))
    for t, v, kind, row in points:
        x, y = main.x(t), main.y(v)
        tip = f"<title>{escape(row['date'])}: {v:.4g} {escape(factor['units'])} — {kind}; {escape(row['source_name'])}</title>"
        if kind == "coded":
            body.append(f'<rect x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8" transform="rotate(45 {x:.1f} {y:.1f})" fill="var(--data)" stroke="var(--surface)" stroke-width="1.5">{tip}</rect>')
        elif kind == "assumption":
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--surface)" stroke="var(--data)" stroke-width="1.5">{tip}</circle>')
        else:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--data)" stroke="var(--surface)" stroke-width="1.5" opacity="0.85">{tip}</circle>')
    if ts:
        body.append(main.vline(max(ts), "last data"))
    today = as_of or date.today()
    if not ts or decimal_year(today) - max(ts) > 0.05 * (main.x1 - main.x0):
        body.append(main.vline(decimal_year(today), f"today {today.isoformat()}"))
    labels = factor.get("phase_labels") or {}
    named: set[str] = set()
    for point in (fit or {}).get("turning_points", {}).get("upcoming", [])[:4]:
        x, y = main.x(point["t"]), main.y(point["value"])
        up = point["type"] == "peak"
        label = labels.get(point["type"]) or point["type"]
        window = point.get("window")
        if window:
            x_lo, x_hi = main.x(decimal_year(date.fromisoformat(window[0]))), main.x(decimal_year(date.fromisoformat(window[1])))
            wy = y - 14 if up else y + 14
            body.append(f'<line x1="{x_lo:.1f}" x2="{x_hi:.1f}" y1="{wy:.1f}" y2="{wy:.1f}" stroke="var(--ink-2)" stroke-width="1.5"/>')
        shape = f"{x - 5:.1f},{y + (3 if up else -3):.1f} {x + 5:.1f},{y + (3 if up else -3):.1f} {x:.1f},{y + (-6 if up else 6):.1f}"
        tip = f"{label} ≈ {point['date']}" + (f" (10–90%: {window[0]} to {window[1]}; support {point['support']:.0%})" if window else f" (support {point['support']:.0%})")
        body.append(f'<polygon points="{shape}" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"><title>{escape(tip)}</title></polygon>')
        text = f"~{point['date'][:4]}" if point["type"] in named else f"{label} ~{point['date'][:4]}"
        named.add(point["type"])
        # Labels sit left of their marker so successive projected extremes never overlap.
        body.append(f'<text x="{x - 8:.1f}" y="{y + (-8 if up else 16):.1f}" text-anchor="end" fill="var(--ink)">{escape(text)}</text>')
    height = top + main.height + 40
    if oscillator:
        response = fit["dynamics"]["impulse_response"]
        lower_top = height + 44
        inset = Panel(lower_top, 120, 0, max(response["years"]), min(min(response["response"]), 0), max(response["response"]))
        body.append(f'<text class="title" x="{LEFT}" y="{lower_top - 24}" style="font-size:14px">Shock response (inertia and whiplash)</text>')
        overshoot = fit["dynamics"].get("overshoot")
        body.append(f'<text class="sub" x="{LEFT}" y="{lower_top - 8}">Path after a one-unit shock; overshoot below zero = {overshoot}. Years after shock on the x-axis.</text>')
        body.append(inset.axes(years=False))
        zero = inset.y(0)
        body.append(f'<line class="axis" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{zero:.1f}" y2="{zero:.1f}"/>')
        body.append(inset.line(response["years"], response["response"], stroke="var(--s1)"))
        height = lower_top + inset.height + 40
    notes = ["Model-derived structural prior, not an observation. The band assumes the fitted dynamics persist; structural breaks are not modelled.", *(fit or {}).get("warnings", [])[:3]]
    lines = _wrap(" ".join(notes), 150)[:4]
    for i, line in enumerate(lines):
        body.append(f'<text class="note" x="{LEFT}" y="{height + 4 + 15 * i:.0f}">{escape(line)}</text>')
    return _svg(height + 15 * len(lines) + 8, "".join(body), title)


def _wrap(text: str, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return [*lines, current] if current else lines


def composite_chart(name: str, result: dict) -> str:
    series = result["series"]
    t = series["t"]
    values = series["value"]
    title = f"{name}: combined cycle factors"
    finite = _finite(values) + _finite(series["lower"]) + _finite(series["upper"])
    if not finite:
        return _svg(120, f'<text class="title" x="{LEFT}" y="32">{escape(title)}</text><text class="sub" x="{LEFT}" y="56">No overlapping data to combine.</text>', title)
    names = [c["name"] for c in result["components"]]
    shown = result.get("component_paths", [])[:7]
    legend = [('<line x1="0" x2="16" y1="0" y2="0" stroke="var(--s1)" stroke-width="2.5"/>', "Composite")]
    legend += [(f'<line x1="0" x2="16" y1="0" y2="0" stroke="var(--s{i + 2})" stroke-width="1.5"/>', path["name"]) for i, path in enumerate(shown)]
    legend_svg, legend_bottom = _legend_rows(legend, 80)
    top = legend_bottom + 28
    # Range follows the composite and band, widened to typical component swings; extremes are clipped.
    component_values = [abs(v) for path in shown for v in _finite(path["z"])]
    spread = sorted(component_values)[int(0.98 * (len(component_values) - 1))] if component_values else 0
    main = Panel(top, 260, t[0], t[-1], min(min(finite), -min(spread, 3.5)), max(max(finite), min(spread, 3.5)))
    body = [f'<text class="title" x="{LEFT}" y="30">{escape(title)}</text>']
    body.append(f'<text class="sub" x="{LEFT}" y="52">{escape("Weighted mean of standardized factors (z-scores); solid = observed, dashed = projection with 80% band")}</text>')
    body.append(f"<defs>{main.clip('composite-plot')}</defs>")
    projected = series["projected"]
    body.append(main.axes(units="z-score"))
    plot = ['<g clip-path="url(#composite-plot)">']
    for i, path in enumerate(shown):
        plot.append(main.line(t, path["z"], stroke=f"var(--s{i + 2})", width=1.25, opacity=0.55))
    plot.append(main.band(t, [lo if p else None for lo, p in zip(series["lower"], projected)], [hi if p else None for hi, p in zip(series["upper"], projected)], fill="var(--s1)"))
    plot.append(main.line(t, [v if not p else None for v, p in zip(values, projected)], stroke="var(--s1)", width=2.5))
    plot.append(main.line(t, [v if p else None for v, p in zip(values, projected)], stroke="var(--s1)", width=2.5, dash="5 4"))
    body += [*plot, "</g>"]
    if len(names) > len(shown):
        body.append(f'<text class="note" x="{WIDTH - RIGHT}" y="{top - 8}" text-anchor="end">{len(names) - len(shown)} more components in the composite, not drawn</text>')
    body.append(legend_svg)
    future = [tt for tt, p in zip(t, projected) if p]
    if future:
        body.append(main.vline(future[0], "projection begins"))
    lower_top = top + main.height + 76
    alignment = Panel(lower_top, 110, t[0], t[-1], 0, 1)
    body.append(f'<text class="title" x="{LEFT}" y="{lower_top - 28}" style="font-size:14px">Phase alignment of fitted cycles</text>')
    body.append(f'<text class="sub" x="{LEFT}" y="{lower_top - 12}">1 = cycles share a phase and reinforce; shown only where at least two components have a defined phase; shaded = projected windows above 0.8</text>')
    for window in result.get("alignment_windows", []):
        x0 = alignment.x(decimal_year(date.fromisoformat(window["start"])))
        x1 = alignment.x(decimal_year(date.fromisoformat(window["end"])))
        body.append(f'<rect x="{x0:.1f}" y="{lower_top}" width="{max(x1 - x0, 2):.1f}" height="{alignment.height}" fill="var(--s1)" opacity="0.12"><title>{escape(window["start"])} to {escape(window["end"])}: shared {escape(window["shared_phase"])}, max {window["max_alignment"]}</title></rect>')
    body.append(alignment.axes())
    y80 = alignment.y(0.8)
    body.append(f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y80:.1f}" y2="{y80:.1f}" stroke="var(--muted)" stroke-dasharray="4 4"/>')
    body.append(alignment.line(t, series["alignment"], stroke="var(--s1)"))
    height = lower_top + alignment.height + 40
    lines = _wrap(" ".join(["Composite inherits each component fit verdict; alignment is phase coherence, not a probability. Interval assumes independent components. Extreme component swings are clipped to the plot.", *result.get("notes", [])[2:]]), 150)[:3]
    for i, line in enumerate(lines):
        body.append(f'<text class="note" x="{LEFT}" y="{height + 4 + 15 * i:.0f}">{escape(line)}</text>')
    return _svg(height + 15 * len(lines) + 8, "".join(body), title)
