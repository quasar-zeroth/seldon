"""Static discovery catalog: models, conventions and starting templates for cycle factors.

Template period ranges are commonly cited values from contested literature. They
bound a period search; they are not evidence that a cycle exists.
"""

from __future__ import annotations

RELEVANCE_FLOOR = 0.25

# One message for every research entry point (handoffs, reruns, built-in prompts, docs).
CYCLE_GUIDANCE = (
    "Cycles: use every relevant cycle prior you can see. The question's cycles context lists factors linked to its "
    "entities and factors matched through the topic relevance lookup (research cycles relevance --scenario ID), "
    "highest relevance first. For each, state the phase or projection at the horizon, its verdict and its relevance, "
    "and use it in base_rate, assumptions, synthesis or case bounds. Let supported cycles with material relevance "
    "shift judgments; weak or under-identified cycles are context and must not override evidence. Record cycle use as "
    "assumption evidence or reasoning, never as an observation. If a recurring pattern emerges that no stored cycle "
    "covers, including very short or unconventional ones (seasonality, earnings or guidance cadence, inventory, "
    "election or policy rhythms), feel free to add it: define a cycle factor with sourced dated data, score its topic "
    "relevance, refit, and cite it as a hypothesis until its verdict supports it."
)

MODELS = {
    "harmonic": {
        "summary": "Trend plus one or more sin/cos cycles (a Fourier series per period) fitted by weighted least squares, with a generalized Lomb-Scargle period search for irregularly dated history.",
        "use_when": "Testing whether a recurring wave with a stable period exists (generational turnings, long waves, political pendulum) and locating its phase and next turning points.",
        "key_parameters": {
            "period_years": "Fix to test one theory's stated period; omit to search period_min_years..period_max_years.",
            "harmonics": "1 = symmetric wave; 2-3 = asymmetric shapes such as slow speculative booms and fast busts.",
            "cycles": "Number of distinct periods fitted jointly (e.g. a long wave plus a business cycle).",
            "trend": "none (mean only), linear or quadratic secular trend.",
        },
        "outputs": "Period with standard error, amplitude, phase, historical and upcoming turning points with timing windows, 80% projection band, red-noise significance, holdout backtest, verdict.",
        "limits": "Assumes a stationary period and phase. Structural breaks, drifting periods and fewer than two observed cycles make phase extrapolation unreliable.",
    },
    "oscillator": {
        "summary": "Stochastic damped cycle: autoregressive AR(p) dynamics around a trend on a regular grid (Yule 1927). Complex roots imply an intrinsic period; their modulus gives damping.",
        "use_when": "Measuring inertia (persistence), momentum and whiplash (overshoot after a shock) in markets, conflict intensity, policy or sentiment, or when cycle length varies from one wave to the next.",
        "key_parameters": {
            "order": "2 is the minimal oscillator and gives a deterministic phase; higher orders capture richer dynamics without a single phase.",
            "step_years": "Resampling interval; heavy interpolation of sparse history inflates persistence.",
        },
        "outputs": "AR coefficients and roots, implied period, damping ratio, half-life, persistence, impulse response and overshoot, probability of oscillation, projection band, backtest, verdict.",
        "limits": "Long-horizon forecasts revert to trend. Interpolation and regime changes bias coefficients. Overshoot describes response to shocks, not timing of the next shock.",
    },
}

CONVENTIONS = {
    "time": "Observations carry ISO dates; models use decimal years.",
    "phase": "Angle of the fitted cyclical component relative to trend: 0 = peak, pi/2 = declining, pi = trough, 3pi/2 = rising. Factor phase_labels rename these quadrants.",
    "weights": "Negative component weights invert a factor; positive lag_years delays its influence.",
    "verdicts": {
        "supported": "Harmonic: beats red-noise surrogates (p < 0.05) with at least two observed cycles and no negative holdout skill vs trend. Oscillator: oscillation in >= 90% of coefficient draws, AIC gain over AR(1) > 2, stationary, at least two implied cycles.",
        "weak": "Fitted but not distinguishable from noise or failing out-of-sample; a hypothesis only.",
        "under-identified": "Fewer than two cycles observed; period/phase cannot be pinned down.",
        "not-oscillatory": "Oscillator found persistence/inertia but no intrinsic cycle.",
    },
    "interpretation": "Fits are model-derived structural priors, never observations. Cite the fit ID, verdict and diagnostics; record any forecast use as an assumption.",
}

EXTENSION_POINTS = {
    "status": "Not implemented; add a fitter in fitting.py, register it in MODELS and FitSpec.model, and cover it in tests/unit/test_cycles.py.",
    "candidates": {
        "hawkes": "Self-exciting point process for event histories (wars, crises): events raise the near-term rate of further events.",
        "wavelet": "Time-varying period/amplitude analysis for drifting cycles.",
        "state_space": "Trend plus stochastic cycle with Kalman filtering (Harvey) for noisy, gappy series.",
    },
}

CAVEATS = (
    "Several quoted ranges come from contested theories. Verify sources and code observations from primary indicators, never from the theory's own phase dates (circular).",
    "Most long cycles have only a handful of historical repetitions; expect under-identified or weak verdicts and say so.",
)

TEMPLATES = {
    "generational-saeculum": {
        "name": "Generational turnings (saeculum)",
        "origin": "Strauss and Howe, The Fourth Turning (1997)",
        "domain": "society",
        "region": "United States / Anglo-American",
        "period_years": [70, 100],
        "low_label": "Individualism, weak institutions, low civic trust",
        "high_label": "Civic cohesion, strong institutions, high collective trust",
        "phase_labels": {"peak": "High", "declining": "Awakening", "trough": "Unraveling", "rising": "Crisis (Fourth Turning)"},
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "coded or measured proxies",
        "proxies": ["Trust in national government", "Confidence in institutions", "Civic association membership", "Political polarization (inverted)"],
        "data_sources": ["American National Election Studies", "Pew Research Center trust in government series", "Gallup confidence in institutions", "V-Dem"],
        "caveats": "Turning dates are author-defined; coding from them is circular. Few complete saecula exist in any one country's records.",
    },
    "kondratiev-long-wave": {
        "name": "Kondratiev long wave",
        "origin": "Kondratiev (1925); Schumpeter's technology waves",
        "domain": "economics",
        "region": "Global / core industrial economies",
        "period_years": [40, 65],
        "low_label": "Long downswing: low growth, deflationary pressure",
        "high_label": "Long upswing: high growth, rising prices and rates",
        "phase_labels": {"peak": "Late upswing / peak", "declining": "Downswing", "trough": "Depression trough", "rising": "Upswing"},
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured",
        "proxies": ["Real GDP per capita growth (smoothed)", "Wholesale price index", "Long-term interest rates"],
        "data_sources": ["Maddison Project Database", "FRED long historical series", "Bank of England 'A millennium of macroeconomic data'"],
        "caveats": "Existence and dating are disputed; price and output waves can disagree.",
    },
    "kuznets-swing": {
        "name": "Kuznets swing",
        "origin": "Kuznets (1930)",
        "domain": "economics",
        "region": "Name the economy",
        "period_years": [15, 25],
        "low_label": "Building and migration slump",
        "high_label": "Infrastructure, construction and migration boom",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured",
        "proxies": ["Housing starts or building permits", "Immigration", "Infrastructure investment share"],
        "data_sources": ["FRED", "National statistical offices"],
    },
    "juglar-investment": {
        "name": "Juglar fixed-investment cycle",
        "origin": "Juglar (1862)",
        "domain": "economics",
        "region": "Name the economy",
        "period_years": [7, 11],
        "low_label": "Investment contraction",
        "high_label": "Investment expansion",
        "fit": {"model": "oscillator", "order": 2},
        "measurement": "measured",
        "proxies": ["Fixed investment share of GDP", "Capacity utilization", "Recession indicators"],
        "data_sources": ["FRED", "NBER business cycle dates"],
    },
    "kitchin-inventory": {
        "name": "Kitchin inventory cycle",
        "origin": "Kitchin (1923)",
        "domain": "economics",
        "region": "Name the economy",
        "period_years": [3, 5],
        "low_label": "Inventory liquidation",
        "high_label": "Inventory accumulation",
        "fit": {"model": "oscillator", "order": 2},
        "measurement": "measured",
        "proxies": ["Inventory-to-sales ratio", "Manufacturing new orders minus inventories"],
        "data_sources": ["FRED"],
    },
    "financial-speculation": {
        "name": "Credit and speculation cycle",
        "origin": "Minsky's financial instability hypothesis; BIS medium-term financial cycle research",
        "domain": "finance",
        "region": "Name the economy",
        "period_years": [10, 25],
        "low_label": "Deleveraging, risk aversion",
        "high_label": "Credit boom, speculative excess",
        "phase_labels": {"peak": "Mania / peak leverage", "declining": "Bust and deleveraging", "trough": "Revulsion and repair", "rising": "Boom and rising speculation"},
        "fit": {"model": "harmonic", "harmonics": 2},
        "measurement": "measured",
        "proxies": ["Credit-to-GDP gap", "Real house prices", "Equity valuation (CAPE)", "Margin debt"],
        "data_sources": ["BIS credit-to-GDP gaps and property prices", "Robert Shiller online data", "FRED"],
        "caveats": "Booms build slowly and collapse fast: use 2-3 harmonics or the oscillator model; peaks are easier to see after the fact.",
    },
    "long-term-debt": {
        "name": "Long-term debt cycle",
        "origin": "Dalio, Principles for Navigating Big Debt Crises (2018)",
        "domain": "finance",
        "region": "Name the economy",
        "period_years": [50, 80],
        "low_label": "Low leverage after deleveraging",
        "high_label": "Peak debt burden",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured",
        "proxies": ["Total debt-to-GDP", "Long-term interest rates (inverted)", "Debt-service ratio"],
        "data_sources": ["IMF Global Debt Database", "BIS total credit statistics"],
        "caveats": "Very few complete repetitions in national data.",
    },
    "great-power-war": {
        "name": "Great-power war intensity",
        "origin": "Goldstein, Long Cycles (1988); Richardson's statistics of deadly quarrels",
        "domain": "conflict",
        "region": "International system",
        "period_years": [40, 120],
        "low_label": "Peace among great powers",
        "high_label": "Intense great-power war",
        "fit": {"model": "oscillator", "order": 2},
        "measurement": "measured",
        "proxies": ["log(1 + battle deaths per 100k world population)", "Great-power war years per decade"],
        "data_sources": ["Correlates of War", "Uppsala Conflict Data Program (UCDP)", "Our World in Data conflict series"],
        "caveats": "War sizes are heavy-tailed; convert events to rates and log-transform. Event histories may suit a future self-exciting (Hawkes) model better.",
    },
    "hegemonic-cycle": {
        "name": "Hegemonic long cycle",
        "origin": "Modelski and Thompson, Seapower in Global Politics (1988)",
        "domain": "conflict",
        "region": "International system",
        "period_years": [90, 130],
        "low_label": "Deconcentrated, contested leadership",
        "high_label": "Concentrated global leadership",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured",
        "proxies": ["Leading power share of global naval capability", "Leading power share of world GDP"],
        "data_sources": ["Modelski-Thompson seapower data", "Maddison Project Database"],
        "caveats": "Roughly five cycles since 1500; strongly under-identified for any single factor series.",
    },
    "globalization-wave": {
        "name": "Globalization versus localization",
        "origin": "Economic history of the 1870-1914 and post-1945 integration waves",
        "domain": "economics",
        "region": "Global",
        "period_years": [40, 120],
        "low_label": "Localized, self-sufficient economies",
        "high_label": "Globalized trade and capital integration",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured",
        "proxies": ["World trade openness (exports + imports / GDP)", "Cross-border capital flows", "Average tariff rates (inverted)"],
        "data_sources": ["Our World in Data trade openness", "Penn World Table", "World Bank World Development Indicators"],
        "caveats": "Only about two clear waves are recorded; expect under-identified verdicts.",
    },
    "political-pendulum": {
        "name": "Political pendulum",
        "origin": "Schlesinger, The Cycles of American History (1986)",
        "domain": "politics",
        "region": "Name the polity; left/right meanings are not universal",
        "period_years": [20, 40],
        "low_label": "Private interest / conservative mood",
        "high_label": "Public purpose / reform mood",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured or coded",
        "proxies": ["Policy mood index", "Party manifesto left-right scores", "Seat or vote shares"],
        "data_sources": ["Manifesto Project", "Stimson policy mood", "National election archives"],
        "caveats": "Define the dimension and region explicitly; avoid a universal left-right scale.",
    },
    "secular-cycle": {
        "name": "Structural-demographic secular cycle",
        "origin": "Turchin and Nefedov, Secular Cycles (2009)",
        "domain": "society",
        "region": "Name the state",
        "period_years": [150, 300],
        "low_label": "Integrative, stable phase",
        "high_label": "Disintegrative phase: elite overproduction, instability",
        "fit": {"model": "harmonic", "harmonics": 1},
        "measurement": "measured or coded",
        "proxies": ["Real wages (inverted)", "Elite overproduction indicators", "Political violence events per year"],
        "data_sources": ["Seshat Global History Databank", "Published political-violence datasets"],
        "caveats": "Requires centuries of data; shorter 'fathers-and-sons' violence oscillations (about 50 years) can be fitted as a second cycle.",
    },
    "policy-whiplash": {
        "name": "Inertia and whiplash dynamics",
        "origin": "Second-order systems: momentum plus corrective feedback produces overshoot",
        "domain": "other",
        "region": "Name the system",
        "period_years": None,
        "low_label": "Below equilibrium",
        "high_label": "Above equilibrium",
        "fit": {"model": "oscillator", "order": 2},
        "measurement": "measured",
        "proxies": ["Policy rates", "Sentiment indices", "Regulatory stringency", "Organizational headcount or priorities"],
        "data_sources": ["Domain-specific series"],
        "caveats": "Measures persistence and overshoot after shocks; does not predict when shocks occur.",
    },
}


def catalog() -> dict:
    return {
        "relevance": {
            "floor": RELEVANCE_FLOOR,
            "meaning": "Topic relevance scores are judged 0-1 strengths of a cycle's bearing on a topic; cycles at or above the floor enter matched questions' forecast context.",
            "guidance": CYCLE_GUIDANCE,
        },
        "models": MODELS,
        "conventions": CONVENTIONS,
        "templates": TEMPLATES,
        "extension_points": EXTENSION_POINTS,
        "caveats": list(CAVEATS),
        "workflow": [
            "research cycles export: reuse existing factors before creating new ones",
            "research cycles apply: define a factor (optionally from a template) with poles, rubric, region and entity links",
            "research cycles import / apply: load dated, sourced observations; preferred fits refresh automatically",
            "research cycles fit --set model=oscillator: compare alternative specifications (recorded, non-preferred)",
            "research cycles discover: search residuals for hidden cycles, then add a factor for any plausible candidate",
            "research cycles combine / chart: compose factors, check alignment and lead/lag, inspect SVG charts",
            "research cycles apply (topics, relevance): score how strongly each cycle bears on reusable research topics",
            "research cycles relevance --scenario: see which cycles a question inherits through its entities and topics",
            "research cycles outlook --scenario: read cycle priors for a forecast and cite them as assumptions",
        ],
    }
