"""Builds report_correction_choice.html: why the A, B + cubic correction model was chosen.

Run:  python make_report.py      (numbers are recomputed from model.py and the Excel data)
The report is one self-contained HTML file with inline SVG charts; it needs no internet.
"""
import html
import math

import numpy as np

import model as m

R = CFG = USED = I = P = C = ROW = LV = None


def _load(cfg=None):
    """Calibrate the default model (A, B + cubic) on the current data and set the module data."""
    global R, CFG, USED, I, P, C, ROW, LV
    CFG = m.clean_config({**m.DEFAULT_CONFIG, **(cfg or {}), "fit_B": 1.0, "correction_degree": 3.0})
    R = m.calibrate(CFG)
    USED = np.array(R["obs"]["used"], bool)
    I, P, C, ROW = m.OBS_I[USED], m.OBS_P[USED], m.OBS_C[USED], m.OBS_ROW[USED]
    LV = [c for c in m.LEVELS if np.any(C == c)]


# ---------------------------------------------------------------- candidate correction shapes
def stage1(Ix, Px, Cx):
    A, B, _, _ = m.fit_AB(Ix, Px, Cx, CFG)
    return A, B


def poly_shape(deg):
    def fit(cp, c, p):
        k = np.polyfit(cp, c, deg) if deg else np.array([1.0, 0.0])
        return lambda x, pp: np.polyval(k, x)
    return fit


def exp_shape(cp, c, p):
    k0 = float(c.min()) - 2
    sl, ic = np.polyfit(cp, np.log(np.maximum(c - k0, 1e-6)), 1)
    th, _ = m.levenberg_marquardt(lambda t: t[0] + math.exp(t[1]) * np.exp(math.exp(t[2]) * cp) - c,
                                  [k0, ic, math.log(max(sl, 1e-4))])
    return lambda x, pp: th[0] + math.exp(th[1]) * np.exp(math.exp(th[2]) * x)


def log_space_shape(cp, c, p):
    x = -np.log(1 - cp / 100)
    xt = -np.log(1 - c / 100)
    w = np.exp(-xt)
    k = np.linalg.lstsq(np.vander(x, 4) * w[:, None], xt * w, rcond=None)[0]
    return lambda xx, pp: 100 * (1 - np.exp(-np.polyval(k, -np.log(1 - np.clip(xx, 0, 99.9) / 100))))


def pressure_shape(cp, c, p):
    def D(x, pp):
        z, lp = x / 50, np.log(pp / 100)
        return np.column_stack([np.ones_like(z), z, z ** 2, z ** 3, lp, z * lp])
    k = np.linalg.lstsq(D(cp, p), c, rcond=None)[0]
    return lambda x, pp: D(x, pp) @ k


SHAPES = [
    ("None (C = Cp)", "physics only", 0, poly_shape(0)),
    ("Linear", "k0 + k1·Cp", 2, poly_shape(1)),
    ("Quadratic", "k0 + k1·Cp + k2·Cp²", 3, poly_shape(2)),
    ("Cubic (chosen)", "k0 + k1·Cp + k2·Cp² + k3·Cp³", 4, poly_shape(3)),
    ("Exponential", "k0 + k1·exp(k2·Cp)", 3, exp_shape),
    ("Log-space cubic", "cubic in −ln(1 − C/100)", 4, log_space_shape),
    ("Cubic + pressure terms", "cubic + ln P + Cp·ln P", 6, pressure_shape),
]


def evaluate(fit_shape):
    A, B = stage1(I, P, C)
    cp = m.c_physics(I, P, A, B, CFG)
    f = fit_shape(cp, C, P)
    pred = f(cp, P)
    grid = np.linspace(cp.min(), cp.max(), 300)
    mono = all(np.all(np.diff(f(grid, np.full_like(grid, pv))) > 0) for pv in (P.min(), 150.0, P.max()))
    lopo = np.empty_like(C)
    for r in np.unique(ROW):
        t = ROW == r
        A2, B2 = stage1(I[~t], P[~t], C[~t])
        cp_tr = m.c_physics(I[~t], P[~t], A2, B2, CFG)
        f2 = fit_shape(cp_tr, C[~t], P[~t])
        lopo[t] = f2(m.c_physics(I[t], P[t], A2, B2, CFG), P[t])
    rmse = lambda e: float(np.sqrt(np.mean(e ** 2)))
    near = np.array(LV)[np.argmin(np.abs(lopo[:, None] - np.array(LV)[None, :]), axis=1)]
    return {"pred": pred, "lopo": lopo, "rmse": rmse(pred - C), "lopo_rmse": rmse(lopo - C),
            "mono": mono, "acc": float(np.mean(near == C) * 100), "cp": cp, "f": f}


NAV_HTML = """<body><header style="position:sticky;top:0;z-index:20;height:56px;display:flex;align-items:center;gap:24px;padding:0 24px;
background:rgba(0,0,0,.72);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid #1f1f1f;font-size:14px">
<a href="/" style="display:flex;align-items:center;gap:10px;font-weight:600;color:#ededed;text-decoration:none">
<span style="width:22px;height:22px;border-radius:50%;background:#fff;color:#000;display:grid;place-items:center;font:700 10px system-ui">O₂</span>
Zirconia<span style="color:#2e2e2e;font-weight:300">/</span><span style="color:#a1a1a1;font-weight:400">Physics model</span></a>
<nav style="display:flex;gap:4px;overflow-x:auto">
<a href="/#predict" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Predict</a>
<a href="/#calibration" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Calibration</a>
<a href="/#optimization" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Optimization</a>
<a href="/#validation" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Validation</a>
<a href="/#parameters" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Parameters</a>
<a href="/#data" style="color:#a1a1a1;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Data</a>
<a href="/report" style="color:#ededed;background:#1f1f1f;text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px">Report</a>
</nav></header>"""


def build_report(cfg=None, nav=False):
    """Return the report as one HTML string. nav=True adds the web app's top menu (used by app.py)."""
    _load(cfg)
    RES = [(name, formula, npar, evaluate(fn)) for name, formula, npar, fn in SHAPES]
    BY = {name: res for name, _, _, res in RES}
    NONE, LIN, CUB = BY["None (C = Cp)"], BY["Linear"], BY["Cubic (chosen)"]
    CP = NONE["cp"]


    # ---------------------------------------------------------------- tiny SVG chart helpers
    INK, INK2, MUTED, GRID, AXIS = "#ededed", "#a1a1a1", "#6e6e6e", "#1d1d1d", "#333"
    ORANGE, WHITE, GREY, BLUE = "#d95926", "#ededed", "#6e6e6e", "#3987e5"
    RAMP = ["#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]


    def lerp(a, b, t):
        pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
        pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


    def level_color(i, n):
        s = (i / max(n - 1, 1)) * (len(RAMP) - 1)
        j = min(int(s), len(RAMP) - 2)
        return lerp(RAMP[j], RAMP[j + 1], s - j)


    def nice_ticks(lo, hi, n=5):
        raw = (hi - lo) / n
        mag = 10 ** math.floor(math.log10(raw))
        e = raw / mag
        step = (10 if e >= 7.5 else 5 if e >= 3.5 else 2 if e >= 1.5 else 1) * mag
        t, v = [], math.ceil(lo / step) * step
        while v <= hi + 1e-9:
            t.append(round(v, 10))
            v += step
        return t


    def fnum(v):
        return f"{v:g}" if abs(v) >= 1 or v == 0 else f"{v:.2g}"


    def legend(items):
        out = []
        for name, color, kind in items:
            sym = (f'<line x1="1" y1="6" x2="17" y2="6" stroke="{color}" stroke-width="2"'
                   f'{" stroke-dasharray=\"4 3\"" if kind == "dash" else ""}/>' if kind in ("line", "dash")
                   else f'<rect x="4" y="1" width="10" height="10" rx="2" fill="{color}"/>' if kind == "bar"
                   else f'<circle cx="9" cy="6" r="4" fill="{color}"/>')
            out.append(f'<span><svg viewBox="0 0 18 12" width="18" height="12">{sym}</svg>{html.escape(name)}</span>')
        return f'<div class="legend">{"".join(out)}</div>'


    def xy_chart(series, xlabel, ylabel, xr=None, yr=None, W=560, H=300, hline=None):
        """series: list of dicts {pts, color, kind: line|dash|dot, r}"""
        ml, mr, mt, mb = 56, 14, 10, 42
        iw, ih = W - ml - mr, H - mt - mb
        xs = [p[0] for s in series if not s.get("noext") for p in s["pts"]]
        ys = [p[1] for s in series if not s.get("noext") for p in s["pts"]]
        x0, x1 = xr or (min(xs), max(xs))
        y0, y1 = yr or (min(ys), max(ys))
        if not yr:
            pad = (y1 - y0) * 0.08 or 1
            y0, y1 = y0 - pad, y1 + pad
        X = lambda v: ml + (v - x0) / (x1 - x0) * iw
        Y = lambda v: mt + ih - (v - y0) / (y1 - y0) * ih
        g = [f'<defs><clipPath id="c{id(series)}"><rect x="{ml}" y="{mt}" width="{iw}" height="{ih}"/></clipPath></defs>']
        for v in nice_ticks(y0, y1):
            if y0 <= v <= y1:
                g.append(f'<line x1="{ml}" x2="{ml + iw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}"/>'
                         f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="tk">{fnum(v)}</text>')
        for v in nice_ticks(x0, x1, 6):
            if x0 <= v <= x1:
                g.append(f'<line y1="{mt}" y2="{mt + ih}" x1="{X(v):.1f}" x2="{X(v):.1f}" stroke="{GRID}"/>'
                         f'<text x="{X(v):.1f}" y="{mt + ih + 17}" text-anchor="middle" class="tk">{fnum(v)}</text>')
        g.append(f'<line x1="{ml}" x2="{ml + iw}" y1="{mt + ih}" y2="{mt + ih}" stroke="{AXIS}"/>')
        if hline is not None:
            g.append(f'<line x1="{ml}" x2="{ml + iw}" y1="{Y(hline):.1f}" y2="{Y(hline):.1f}" stroke="#555"/>')
        body = []
        for s in series:
            if s["kind"] in ("line", "dash"):
                d = "".join(("M" if i == 0 else "L") + f"{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(s["pts"]))
                body.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="{s.get("w", 2)}"'
                            f'{" stroke-dasharray=\"5 4\"" if s["kind"] == "dash" else ""} stroke-linejoin="round"/>')
            else:
                r = s.get("r", 3)
                body += [f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="{r}" fill="{s["color"]}" stroke="#0a0a0a" stroke-width="1"'
                         f'{" fill-opacity=\"" + str(s["op"]) + "\"" if "op" in s else ""}/>' for x, y in s["pts"]]
        g.append(f'<g clip-path="url(#c{id(series)})">{"".join(body)}</g>')
        g.append(f'<text x="{ml + iw / 2}" y="{H - 4}" text-anchor="middle" class="al">{html.escape(xlabel)}</text>'
                 f'<text transform="translate(13,{mt + ih / 2}) rotate(-90)" text-anchor="middle" class="al">{html.escape(ylabel)}</text>')
        return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(ylabel)}">{"".join(g)}</svg>'


    def bar_chart(groups, series_names, colors, ylabel, xlabel, W=560, H=300, signed=False, hl=None):
        ml, mr, mt, mb = 56, 14, 10, 42
        iw, ih = W - ml - mr, H - mt - mb
        vals = [v for _, vs in groups for v in vs]
        lo = min(0, min(vals)) * (1.12 if signed else 1)
        hi = max(vals) * 1.12 if max(vals) > 0 else 1
        Y = lambda v: mt + ih - (v - lo) / (hi - lo) * ih
        g = []
        for v in nice_ticks(lo, hi):
            if lo <= v <= hi:
                g.append(f'<line x1="{ml}" x2="{ml + iw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}"/>'
                         f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="tk">{fnum(v)}</text>')
        gw = iw / len(groups)
        n = len(series_names)
        bw = min(26, (gw * 0.72 - 2 * (n - 1)) / n)
        for gi, (label, vs) in enumerate(groups):
            cx = ml + gw * gi + gw / 2
            x = cx - (n * bw + 2 * (n - 1)) / 2
            if hl is not None and gi == hl:
                g.append(f'<rect x="{ml + gw * gi + 2:.1f}" y="{mt}" width="{gw - 4:.1f}" height="{ih}" fill="#fff" fill-opacity=".05" rx="4"/>')
            for si, v in enumerate(vs):
                top, bot = (Y(v), Y(0)) if v >= 0 else (Y(0), Y(v))
                g.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 0.5):.1f}" rx="2" fill="{colors[si]}"/>')
                x += bw + 2
            g.append(f'<text x="{cx:.1f}" y="{mt + ih + 17}" text-anchor="middle" class="tk">{html.escape(label)}</text>')
        g.append(f'<line x1="{ml}" x2="{ml + iw}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="{AXIS}"/>'
                 f'<text x="{ml + iw / 2}" y="{H - 4}" text-anchor="middle" class="al">{html.escape(xlabel)}</text>'
                 f'<text transform="translate(13,{mt + ih / 2}) rotate(-90)" text-anchor="middle" class="al">{html.escape(ylabel)}</text>')
        return (legend([(s, c, "bar") for s, c in zip(series_names, colors)]) +
                f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(ylabel)}">{"".join(g)}</svg>')


    def fig(title, caption, svg):
        return f'<figure><figcaption><b>{title}</b><span>{caption}</span></figcaption>{svg}</figure>'


    # ---------------------------------------------------------------- figures
    lvl_lab = [f"{c:g}" for c in LV]
    bias = lambda pred: [float(np.mean((pred - C)[C == c])) for c in LV]
    mae = lambda pred: [float(np.mean(np.abs(pred - C)[C == c])) for c in LV]

    # 1. model comparison (all variants from the app)
    comp = R["comparison"]
    short = {"Theory (A = B = 1)": "Theory", "Only A (B = 1)": "Only A", "A and B": "A, B",
             "Only A + linear": "A + lin", "A, B + linear": "A,B + lin", "Only A + cubic": "A + cubic",
             "A, B + cubic": "A,B + cubic"}
    fig1 = bar_chart([(short[v["label"]], [v["fit"]["RMSE"], v["lopo"]["RMSE"]]) for v in comp],
                     ["fit on all data", "unseen pressures"], [GREY, WHITE], "RMSE (% O₂)", "model", W=1000, hl=len(comp) - 1)

    # 2. bias per level: the shape problem
    fig2 = bar_chart(list(zip(lvl_lab, zip(bias(NONE["pred"]), bias(LIN["pred"]), bias(CUB["pred"])))),
                     ["physics only (A, B)", "+ linear", "+ cubic"], [ORANGE, GREY, WHITE],
                     "mean error (pred − actual, %)", "actual O₂ (%)", signed=True)

    # 3. the correction map
    cpg = np.linspace(CP.min(), CP.max(), 200)
    pts_lv = [{"pts": list(zip(CP[C == c], C[C == c])), "color": level_color(i, len(LV)), "kind": "dot", "r": 2.6}
              for i, c in enumerate(LV)]
    fig3 = legend([("identity C = Cp", "#555", "dash"), ("linear fit", ORANGE, "line"), ("cubic fit (chosen)", WHITE, "line"),
                   ("readings (dark = 21 %, light = 95 %)", BLUE, "dot")]) + xy_chart(
        pts_lv + [{"pts": [(0, 0), (100, 100)], "color": "#555", "kind": "dash", "noext": True, "w": 1.5},
                  {"pts": list(zip(cpg, LIN["f"](cpg, cpg))), "color": ORANGE, "kind": "line"},
                  {"pts": list(zip(cpg, CUB["f"](cpg, cpg))), "color": WHITE, "kind": "line"}],
        "physics output Cp (%)", "actual O₂ (%)", xr=(10, 100), yr=(10, 100))

    # 4. difference from identity: what each correction actually does
    fig4 = legend([("actual − Cp, mean per level", BLUE, "dot"), ("linear: correction − Cp", ORANGE, "line"),
                   ("cubic: correction − Cp", WHITE, "line")]) + xy_chart(
        [{"pts": [(float(np.mean(CP[C == c])), float(np.mean(C[C == c] - CP[C == c]))) for c in LV], "color": BLUE, "kind": "dot", "r": 4.5},
         {"pts": list(zip(cpg, LIN["f"](cpg, cpg) - cpg)), "color": ORANGE, "kind": "line"},
         {"pts": list(zip(cpg, CUB["f"](cpg, cpg) - cpg)), "color": WHITE, "kind": "line"}],
        "physics output Cp (%)", "change applied (% O₂)", xr=(10, 100), hline=0)

    # 5. shapes tried
    fig5 = bar_chart([(n.replace(" (chosen)", "").replace("Cubic + pressure terms", "Cubic+P").replace("Log-space cubic", "Log-space")
                       .replace("None (C = Cp)", "None").replace("Exponential", "Exp"), [r["rmse"], r["lopo_rmse"]]) for n, _, _, r in RES],
                     ["fit on all data", "unseen pressures"], [GREY, WHITE], "RMSE (% O₂)", "correction shape", hl=3)

    # 6. MAE per level before/after
    fig6 = bar_chart(list(zip(lvl_lab, zip(mae(NONE["lopo"]), mae(CUB["lopo"])))), ["physics only (A, B)", "physics + cubic"],
                     [ORANGE, WHITE], "MAE on unseen pressures (%)", "actual O₂ (%)")

    # 7. parity: unseen predictions
    fig7 = legend([("physics only (A, B)", ORANGE, "dot"), ("physics + cubic", WHITE, "dot"), ("45° line", "#555", "dash")]) + xy_chart(
        [{"pts": [(0, 0), (100, 100)], "color": "#555", "kind": "dash", "noext": True, "w": 1.5},
         {"pts": list(zip(C - 0.9, NONE["lopo"])), "color": ORANGE, "kind": "dot", "r": 2.4, "op": .85},
         {"pts": list(zip(C + 0.9, CUB["lopo"])), "color": WHITE, "kind": "dot", "r": 2.4, "op": .85}],
        "actual O₂ (%)", "predicted on unseen pressure (%)", xr=(15, 100), yr=(10, 100))

    # 8. slope of the cubic across the band (monotonic check)
    kk = np.asarray(R["corrected"]["k"])
    slope = kk[1] + 2 * kk[2] * cpg + 3 * kk[3] * cpg ** 2
    fig8 = xy_chart([{"pts": list(zip(cpg, slope)), "color": WHITE, "kind": "line"},
                     {"pts": [(cpg[0], 1), (cpg[-1], 1)], "color": "#555", "kind": "dash", "w": 1.5}],
                    "physics output Cp (%)", "slope dC/dCp", yr=(0, max(1.6, float(slope.max()) * 1.1)))


    # confusion matrix (unseen, cubic)
    def confusion(pred):
        near = np.array(LV)[np.argmin(np.abs(pred[:, None] - np.array(LV)[None, :]), axis=1)]
        head = "".join(f"<th>{c:g}</th>" for c in LV)
        rows = []
        for a in LV:
            cells = []
            for p in LV:
                n = int(np.sum((C == a) & (near == p)))
                cls = "d" if a == p else ("o" if n else "")
                cells.append(f'<td class="{cls}">{n if n else "·"}</td>')
            ok = int(np.sum((C == a) & (near == a)))
            rows.append(f"<tr><th>{a:g}</th>{''.join(cells)}<td class='t'>{ok}/{int(np.sum(C == a))}</td></tr>")
        return f'<table class="cm"><thead><tr><th>actual \\ pred</th>{head}<th>correct</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


    # ---------------------------------------------------------------- page
    ph, co = R["physics"], R["corrected"]
    kc = co["k_centered"]
    lin_k = np.polyfit(CP, C, 1)
    cub_row = next(v for v in comp if v["label"] == "A, B + cubic")
    shape_rows = "".join(
        f"<tr{' class=sel' if 'chosen' in n else ''}><td class='l'>{html.escape(n)}</td><td class='l mono'>{html.escape(f)}</td>"
        f"<td>{npar}</td><td>{r['rmse']:.3f}</td><td>{r['lopo_rmse']:.3f}</td><td>{r['acc']:.1f} %</td>"
        f"<td>{'yes' if r['mono'] else '<span class=bad>no</span>'}</td></tr>" for n, f, npar, r in RES)
    comp_rows = "".join(
        f"<tr{' class=sel' if v['label'] == 'A, B + cubic' else ''}><td class='l'>{html.escape(v['label'])}</td><td>{v['n_params']}</td>"
        f"<td>{v['A']:.4f}</td><td>{v['B']:.4f}</td><td>{v['fit']['RMSE']:.3f}</td><td>{v['lopo']['RMSE']:.3f}</td>"
        f"<td>{v['level_acc']:.1f} %</td></tr>" for v in comp)
    press = BY["Cubic + pressure terms"]
    b_none = bias(NONE["pred"])

    PAGE = f"""<!DOCTYPE html>
    <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Zirconia O₂ model: why the cubic correction</title>
    <style>
    :root{{color-scheme:dark}}
    *{{box-sizing:border-box}}
    body{{margin:0;background:#000;color:{INK};font:15px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}}
    main{{max-width:1080px;margin:0 auto;padding:56px 28px 80px}}
    h1{{font-size:36px;letter-spacing:-.03em;line-height:1.15;margin:0 0 12px}}
    h2{{font-size:22px;letter-spacing:-.02em;margin:48px 0 10px;padding-top:28px;border-top:1px solid #1f1f1f}}
    p,li{{color:{INK2};max-width:800px}} b,strong{{color:{INK}}}
    .eyebrow{{font:12px ui-monospace,Menlo,monospace;color:{MUTED};letter-spacing:.08em;text-transform:uppercase}}
    .lead{{font-size:17px;color:{INK2}}}
    .box{{border:1px solid #2e2e2e;border-radius:12px;padding:18px 22px;background:#0a0a0a;margin:20px 0}}
    .box p{{margin:6px 0}}
    .eq{{font:14px/1.7 ui-monospace,Menlo,monospace;background:#000;border:1px solid #1f1f1f;border-radius:8px;padding:12px 14px;overflow-x:auto;white-space:nowrap;color:#e6e6e6;margin:10px 0}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    @media(max-width:860px){{.grid{{grid-template-columns:1fr}}}}
    figure{{margin:0;background:#0a0a0a;border:1px solid #1f1f1f;border-radius:12px;padding:18px}}
    figcaption b{{display:block;font-size:14px;margin-bottom:2px}} figcaption span{{display:block;color:{INK2};font-size:13px;margin-bottom:10px}}
    svg{{width:100%;height:auto;display:block}}
    .tk{{fill:{MUTED};font:11px ui-monospace,Menlo,monospace}} .al{{fill:{INK2};font-size:12px}}
    .legend{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:{INK2};margin-bottom:6px}} .legend span{{display:inline-flex;gap:6px;align-items:center}}
    .legend svg{{width:18px;height:12px;flex:none;display:inline-block}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th,td{{padding:8px 10px;border-bottom:1px solid #1f1f1f;text-align:right;white-space:nowrap}}
    th{{color:{MUTED};font-weight:500;font-size:12px}} td{{font-family:ui-monospace,Menlo,monospace}}
    td.l,th.l{{text-align:left;font-family:inherit}} .mono{{font-family:ui-monospace,Menlo,monospace!important;color:{INK2}}}
    tr.sel td{{background:#161616;color:#fff}} .bad{{color:#f87171}}
    .tbl{{border:1px solid #1f1f1f;border-radius:12px;overflow-x:auto;background:#0a0a0a}}
    .cm td,.cm th{{text-align:center;padding:6px 7px}} .cm td.d{{background:#1c5cab;color:#fff}} .cm td.o{{background:#3a2412;color:#f5b38a}} .cm td.t{{color:{INK2}}}
    .kpis{{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid #1f1f1f;border-radius:12px;overflow:hidden;margin:20px 0}}
    @media(max-width:860px){{.kpis{{grid-template-columns:1fr 1fr}}}}
    .kpis div{{padding:16px 18px;border-right:1px solid #1f1f1f}} .kpis div:last-child{{border:0}}
    .kpis small{{color:{MUTED};font-size:12px;display:block}} .kpis strong{{font-size:26px;letter-spacing:-.03em}}
    footer{{color:{MUTED};font-size:12px;margin-top:48px}}
    </style></head><body><main>
    <p class="eyebrow">Zirconia O₂ sensor · model selection report</p>
    <h1>Why the model uses A, B and a cubic correction</h1>
    <p class="lead">The model turns pressure P and sensor current I into oxygen concentration C. It has two stages: a physics stage with
    coefficients A and B, then a correction applied to the physics result. This report explains why the correction is a cubic,
    and why a straight-line (linear) correction was not used, with the evidence from the data.</p>

    <div class="kpis">
     <div><small>Readings used</small><strong>{int(USED.sum())}</strong><small>of {len(USED)} (21–95 % O₂, 27 pressures)</small></div>
     <div><small>Physics only (A, B)</small><strong>{NONE['lopo_rmse']:.2f} %</strong><small>RMSE on unseen pressures</small></div>
     <div><small>Physics + linear</small><strong>{LIN['lopo_rmse']:.2f} %</strong><small>no real improvement</small></div>
     <div><small>Physics + cubic (chosen)</small><strong>{CUB['lopo_rmse']:.2f} %</strong><small>{100 * (1 - CUB['lopo_rmse'] / NONE['lopo_rmse']):.0f} % lower error</small></div>
    </div>

    <div class="box">
    <p><b>Decision.</b> Use <b>A, B + cubic correction</b>. It has the lowest error on pressures the model never saw ({CUB['lopo_rmse']:.2f} %),
    puts {CUB['acc']:.0f} % of unseen readings on the correct concentration level (physics only: {NONE['acc']:.0f} %), and it always increases,
    so a higher current always gives a higher concentration.</p>
    <p><b>Why not linear.</b> The best straight line is C = {lin_k[1]:.2f} + {lin_k[0]:.3f}·Cp, which is almost exactly “no change”.
    A and B already make every straight-line adjustment, so a line has nothing left to fix. The remaining error is a <i>bend</i>, and only a curve can remove it.</p>
    </div>

    <h2>1. The final formula</h2>
    <p><b>Stage 1, physics</b> (A and B fitted by Levenberg–Marquardt least squares):</p>
    <div class="eq">Cp = 100·[1 − exp(−(I·R·T·L / 4·F·S·P)·(A/Dk + B/Db))]&nbsp;&nbsp; with A = {ph['A']:.4f}, B = {ph['B']:.4f}</div>
    <p><b>Stage 2, correction</b> (fitted by ordinary least squares):</p>
    <div class="eq">C = {co['k'][0]:.3f} {co['k'][1]:+.4f}·Cp {co['k'][2]:+.5f}·Cp² {co['k'][3]:+.7f}·Cp³</div>
    <p>The same curve written around the middle of the data (Cp = {kc['center']:.1f} %) shows what it really does:</p>
    <div class="eq">C = {kc['b'][0]:.2f} {kc['b'][1]:+.3f}·(Cp − {kc['center']:.1f}) {kc['b'][2]:+.5f}·(Cp − {kc['center']:.1f})² {kc['b'][3]:+.6f}·(Cp − {kc['center']:.1f})³</div>
    <p>At Cp = {kc['center']:.1f} % it returns {kc['b'][0]:.1f} % with slope {kc['b'][1]:.2f}: close to “no change”, plus a small S-shaped bend.
    The constant {co['k'][0]:.1f} in the first form is <b>not</b> an amount added to every reading. It is where the curve would cross Cp = 0,
    far outside the data (Cp {co['lo']:.1f}–{co['hi']:.1f} %), and the code never uses the cubic there: outside that band it continues as a straight line.</p>

    <h2>2. The problem the correction has to fix</h2>
    <p>With A and B optimized, the physics model is unbiased <i>on average</i>, but the errors follow a clear pattern by concentration:
    21 % comes out {abs(b_none[0]):.1f} % too low, 30 % comes out {b_none[1]:.1f} % too high, and the high end is off again. This is a shape problem.
    A and B can only stretch the curve at each pressure; they cannot bend it.</p>
    <div class="grid">
    {fig("Mean error per concentration", "Bars below zero: the model predicts too low. The linear correction (grey) leaves the pattern almost unchanged; the cubic (white) flattens it.", fig2)}
    {fig("What each correction changes", "Blue dots: how far the true value is from the physics output, averaged per level. The orange line (linear) is almost flat at zero; the white line (cubic) follows the dots.", fig4)}
    </div>

    <h2>3. Why linear does not help and cubic does</h2>
    <p>Plot the physics output against the true concentration. If the physics were perfect, every point would sit on the dashed identity line.
    The best straight line through the points lands on top of the identity line. The cubic follows the bend that the points actually make.</p>
    <div class="grid">
    {fig("Correction map: physics output → true concentration", "Each dot is a reading. Linear ≈ identity; the cubic bends where the data bends.", fig3)}
    {fig("The cubic always rises", "Slope of the cubic across the calibrated band. It stays above zero everywhere, so the correction never reverses the order of readings. The dashed line is slope 1 (no change).", fig8)}
    </div>

    <h2>4. Every correction shape that was tried</h2>
    <p>All shapes use the same Stage 1 (A and B) and the same {int(USED.sum())} readings. “Unseen” = leave-one-pressure-out: the model is refitted 27 times,
    each time predicting the one pressure it did not see. That is the fair test, because extra parameters can always lower the error on data the model was fitted to.</p>
    <div class="tbl"><table>
    <thead><tr><th class="l">Correction</th><th class="l">Formula</th><th>Parameters</th><th>RMSE fit</th><th>RMSE unseen</th><th>Correct level (unseen)</th><th>Always rising</th></tr></thead>
    <tbody>{shape_rows}</tbody></table></div>
    <div class="grid" style="margin-top:16px">
    {fig("Error by correction shape", "Grey: fitted data. White: unseen pressures. The highlighted group is the chosen cubic.", fig5)}
    <div class="box" style="margin:0">
    <p><b>How to read this</b></p>
    <p>• <b>Linear</b> gives nothing: it collapses to C ≈ Cp.</p>
    <p>• <b>Exponential</b> (the form used for the earlier 21–40 % data) puts a second exponential on top of the physics exponential and cannot follow 21–95 %.</p>
    <p>• <b>Log-space</b> is worse and does not always rise, so a higher current could give a lower concentration.</p>
    <p>• <b>Quadratic</b> barely helps: one bend is not enough for the S-shape in the data.</p>
    <p>• <b>Cubic + pressure terms</b> is {CUB['lopo_rmse'] - press['lopo_rmse']:.2f} % better on unseen data, but needs 2 more parameters and makes the correction depend on pressure, which A and B are meant to handle.
    The cubic is the simplest shape that captures the bend.</p>
    </div></div>

    <h2>5. Is it worth optimizing B, and the correction?</h2>
    <p>Each part of the model was switched on one at a time. Optimizing only A already beats the textbook theory; adding B helps more;
    the cubic correction gives the largest single gain. A linear correction adds nothing in either case.</p>
    {fig("Error by model", "Grey: fitted data. White: unseen pressures. The highlighted group is the chosen model.", fig1)}
    <div class="tbl" style="margin-top:16px"><table>
    <thead><tr><th class="l">Model</th><th>Params</th><th>A</th><th>B</th><th>RMSE</th><th>Unseen</th><th>Correct level</th></tr></thead>
    <tbody>{comp_rows}</tbody></table></div>

    <h2>6. Accuracy on unseen pressures</h2>
    <div class="grid">
    {fig("Mean absolute error per concentration (unseen)", "The cubic correction cuts the error at 21–35 % sharply. At 80–85 % some error remains; those columns contain sudden jumps that look like transcription errors.", fig6)}
    {fig("Actual vs predicted (unseen)", "Each column is one concentration level (the two models are offset slightly). White points sit closer to the 45° line.", fig7)}
    </div>
    <h3 style="margin-top:22px;font-size:15px">Confusion matrix, physics + cubic, unseen pressures</h3>
    <p>Each prediction is rounded to the nearest concentration level. Blue = correct, orange = off by one level. No prediction is off by more than one level.</p>
    <div class="tbl" style="padding:6px">{confusion(CUB['lopo'])}</div>

    <h2>7. Limits and next steps</h2>
    <ul>
    <li><b>The correction is empirical.</b> It is a calibration curve chosen from the data, not derived from physics. A and B keep their physical meaning; the cubic only fixes the remaining shape. Refit it if the sensor or operating conditions change.</li>
    <li><b>Valid range:</b> P {R['ranges']['P'][0]:g}–{R['ranges']['P'][1]:g} (assumed kPa), C {R['ranges']['C'][0]:g}–{R['ranges']['C'][1]:g} % O₂. Outside it the result is an extrapolation.</li>
    <li><b>Data quality.</b> {int((~USED).sum())} readings were excluded as outliers (the whole “60 %” column, which reads like ~49 %, and the first three 95 % readings). The 85 % column jumps by ~30 µA from P = 144.2 and the 80 % column steps near P = 360. Checking these against the original notebook is the most likely way to reduce the error further.</li>
    <li><b>Weakest levels:</b> 80–85 % (the jumps above). At 95 % the physics-only model is slightly better than the cubic, because the cubic flattens near the top.</li>
    </ul>
    <footer>Generated by make_report.py from {html.escape(R['source'])} · {int(USED.sum())} readings · all errors in % O₂ · no external resources</footer>
    </main></body></html>"""

    if nav:
        PAGE = PAGE.replace("<body><main>", NAV_HTML + "<main>", 1)
    return PAGE, RES

if __name__ == "__main__":
    page, res = build_report()
    with open("report_correction_choice.html", "w", encoding="utf-8") as fh:
        fh.write(page)
    print("wrote report_correction_choice.html")
    for n, f, npar, r in res:
        print(f"{n:24s} fit {r['rmse']:.3f}  unseen {r['lopo_rmse']:.3f}  acc {r['acc']:.1f}  monotone {r['mono']}")
