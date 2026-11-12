"""Physics model, A/B optimizer and calibration for the zirconia O2 sensor."""
import json
import math
import os
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zirconia_sensor_experimental_data.xlsx")
LEVELS = np.array([21.0, 30.0, 35.0, 40.0])          # % O2 of columns 2..5

F_CONST = 96485.33212       # C/mol
R_CONST = 8.314462618       # J/(mol K)

# Sensor and operating parameters. Replace these with the real sensor specs.
# The geometry values are representative placeholders. Changing them rescales A and B,
# but the fitted predictions stay the same, because A and B absorb any constant factor.
DEFAULT_CONFIG = {
    "T": 973.15,          # K, operating temperature (700 C)
    "a": 5.0e-7,          # m, pore radius
    "S": 1.0e-10,         # m^2, diffusion cross-section
    "L": 1.0e-3,          # m, diffusion barrier thickness
    "M": 0.031998,        # kg/mol, O2 molar mass
    "D0": 1.8e-5,         # m^2/s, O2 bulk diffusivity at 273 K and P0
    "alpha": 1.75,        # temperature exponent
    "P0": 101.325,        # reference pressure, in the same unit as the data (kPa)
    "P_to_Pa": 1000.0,    # data pressure unit -> Pa (kPa = 1000)
    "I_to_A": 1.0e-6,     # data current unit -> A (uA = 1e-6)
}

# Backup copy of the spreadsheet values, used if the .xlsx file is not found.
FALLBACK_ROWS = [
    [56.89, 8.082, 17.89, 19.78, 21.27], [62.65, 8.132, 18.85, 20.53, 21.56],
    [65.71, 9.011, 19.22, 21.09, 22.56], [72.76, 9.143, 19.63, 21.16, 23.78],
    [78.72, 9.289, 19.9, 22.84, 23.91], [87.72, 9.801, 20.5, 23.46, 24.45],
    [92.18, 8.901, 21.45, 24.47, 25.94], [106, 9.221, 21.85, 24.99, 26.94],
    [116.5, 9.506, 22.26, 25.86, 27.19], [128.5, 9.612, 22.93, 26.56, 28.88],
    [144.2, 10.012, 23.49, 27.4, 29.89], [155.5, 10.613, 24.05, 27.98, 30.76],
    [171.1, 9.879, 24.67, 28.66, 31.56], [188.3, 9.992, 23.06, 29.37, 32.99],
    [207.9, 10.132, 25.49, 29.96, 32.93], [227.9, 10.161, 26.04, 30.49, 33.8],
    [250.5, 10.952, 26.44, 30.91, 34.68], [273.7, 11.321, 26.76, 31.48, 35.091],
    [301.4, 11.541, 27.22, 31.99, 35.04], [329.8, 11.608, 27.47, 32.33, 36.01],
    [360.3, 11.928, 27.88, 32.741, 36.93], [393.1, 12.021, 28.16, 33.06, 36.53],
    [428.1, 12.512, 28.08, 33.26, 36.88], [465.9, 12.696, 28.1, 33.58, 37.19],
    [506.1, 12.88, 28.27, 33.87, 37.49], [549, 12.94, 28.43, 34.08, 37.73],
    [595, 12.993, 28.7, 34.3, 37.93],
]


# ---------- Data loading (standard library xlsx reader, no openpyxl needed) ----------
def read_xlsx_first_sheet(path):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.find("m:sheetData", ns).findall("m:row", ns):
        vals = []
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            if v is None:
                vals.append(None)
            elif c.get("t") == "s":
                vals.append(shared[int(v.text)])
            else:
                vals.append(float(v.text))
        rows.append(vals)
    return rows


def load_dataset(path=DATA_FILE):
    try:
        raw = read_xlsx_first_sheet(path)
        rows = [r[:5] for r in raw[1:] if r and all(isinstance(x, float) for x in r[:5])]
        source = os.path.abspath(path)
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
        rows, source = FALLBACK_ROWS, "embedded fallback copy"
    arr = np.array(rows, dtype=float)
    return arr[:, 0], arr[:, 1:], source


P_ROWS, I_TABLE, DATA_SOURCE = load_dataset()
# Long format: one observation per (pressure, concentration)
OBS_P = np.repeat(P_ROWS, len(LEVELS))
OBS_I = I_TABLE.ravel()
OBS_C = np.tile(LEVELS, len(P_ROWS))
OBS_ROW = np.repeat(np.arange(len(P_ROWS)), len(LEVELS))
print(f"Loaded {len(P_ROWS)} pressures x {len(LEVELS)} concentrations = {len(OBS_C)} observations from {DATA_SOURCE}")


# ---------- Physics ----------
def knudsen_D(cfg):
    """Dk = (2a/3) * sqrt(8RT / (pi M))   [m^2/s]"""
    return (2.0 * cfg["a"] / 3.0) * math.sqrt(8.0 * R_CONST * cfg["T"] / (math.pi * cfg["M"]))


def bulk_D(P, cfg):
    """Db(T,P) = D0 (T/273)^alpha (P0/P)   [m^2/s]   (P and P0 in the same unit)"""
    return cfg["D0"] * (cfg["T"] / 273.0) ** cfg["alpha"] * (cfg["P0"] / np.asarray(P, float))


def basis(I, P, cfg):
    """Split the exponent u = I R T L / (4 F S P) * (A/Dk + B/Db) into u = A*p + B*q."""
    I_si = np.asarray(I, float) * cfg["I_to_A"]
    P_si = np.asarray(P, float) * cfg["P_to_Pa"]
    K = I_si * R_CONST * cfg["T"] * cfg["L"] / (4.0 * F_CONST * cfg["S"] * P_si)
    return K / knudsen_D(cfg), K / bulk_D(P, cfg)


def c_physics(I, P, A, B, cfg):
    """C = 100 [1 - exp(-(I R T L / 4 F S P)(A/Dk + B/Db))]"""
    p, q = basis(I, P, cfg)
    return 100.0 * (1.0 - np.exp(-(A * p + B * q)))


def current_physics(C, P, A, B, cfg):
    """Forward model: I = -(4 F S P Deff / R T L) ln(1 - C/100), in data units."""
    p1, q1 = basis(1.0, P, cfg)                       # exponent per unit current
    return -np.log(1.0 - np.asarray(C, float) / 100.0) / (A * p1 + B * q1)


def correction(Cp, k):
    """Result correction: C = k0 + k1 * exp(k2 * C_phys)   (monotonic if k1, k2 > 0)"""
    return k[0] + k[1] * np.exp(k[2] * np.asarray(Cp, float))


def correction_inverse(C, k):
    C = np.asarray(C, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log((C - k[0]) / k[1]) / k[2]


# ---------- Optimizer: Levenberg-Marquardt written in numpy ----------
def numeric_jacobian(fun, x, r0):
    J = np.empty((r0.size, x.size))
    for j in range(x.size):
        h = 1e-6 * max(1.0, abs(x[j]))
        xp, xm = x.copy(), x.copy()
        xp[j] += h
        xm[j] -= h
        J[:, j] = (fun(xp) - fun(xm)) / (2 * h)
    return J


def levenberg_marquardt(fun, x0, max_iter=300, tol=1e-12, record=None):
    """Minimise sum(fun(x)^2). Returns x and the iteration history."""
    x = np.array(x0, float)
    r = fun(x)
    cost = float(r @ r)
    lam = 1e-3
    hist = [{"it": 0, "x": x.tolist(), "loss": cost, "lam": lam}]
    for it in range(1, max_iter + 1):
        J = numeric_jacobian(fun, x, r)
        g, H = J.T @ r, J.T @ J
        improved = False
        while lam < 1e14:
            step = np.linalg.solve(H + lam * np.diag(np.diag(H) + 1e-15), -g)
            x_new = x + step
            r_new = fun(x_new)
            c_new = float(r_new @ r_new)
            if np.isfinite(c_new) and c_new < cost:
                improved = True
                break
            lam *= 4.0
        if not improved:
            break
        rel = (cost - c_new) / max(cost, 1e-300)
        x, r, cost, lam = x_new, r_new, c_new, max(lam / 3.0, 1e-15)
        hist.append({"it": it, "x": x.tolist(), "loss": cost, "lam": lam})
        if rel < tol or np.linalg.norm(step) < tol * (np.linalg.norm(x) + tol):
            break
    return x, hist


def metrics(pred, actual):
    e = np.asarray(pred) - np.asarray(actual)
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    out = {
        "MAE": float(np.mean(np.abs(e))),
        "RMSE": float(np.sqrt(np.mean(e ** 2))),
        "R2": float(1 - np.sum(e ** 2) / ss_tot) if ss_tot > 0 else float("nan"),
        "MaxAE": float(np.max(np.abs(e))),
        "Bias": float(np.mean(e)),
        "SSE": float(np.sum(e ** 2)),
    }
    out["per_level"] = {f"{c:g}": float(np.mean(np.abs(e[actual == c]))) for c in LEVELS if np.any(actual == c)}
    return out


# ---------- Calibration ----------
def fit_AB(I, P, C, cfg, start=(1.0, 1.0)):
    """Stage 1: find A, B > 0 minimising sum (C_phys - C_actual)^2.

    1. Linearize: -ln(1 - C/100) = A p + B q is linear in A and B, so ordinary least squares gives a
       closed-form estimate.
    2. Refine with Levenberg-Marquardt on the real concentration error. The parameters are
       log A and log B, which keeps both positive. LM is started from the theory point (1, 1)
       and from the linear estimate, and the run with the lower loss is kept.
    """
    p, q = basis(I, P, cfg)
    X = -np.log(1.0 - C / 100.0)
    lin = np.linalg.lstsq(np.column_stack([p, q]), X, rcond=None)[0]
    lin = np.maximum(lin, 1e-12)

    def resid(theta):
        return c_physics(I, P, math.exp(theta[0]), math.exp(theta[1]), cfg) - C

    best = None
    for s in (np.log(start), np.log(lin)):
        th, hist = levenberg_marquardt(resid, s)
        if best is None or hist[-1]["loss"] < best[1][-1]["loss"] - 1e-12:
            best = (th, hist)
    th, hist = best
    A, B = math.exp(th[0]), math.exp(th[1])
    for h in hist:
        h["A"], h["B"] = math.exp(h["x"][0]), math.exp(h["x"][1])
    return A, B, hist, {"A": float(lin[0]), "B": float(lin[1])}


def fit_correction(Cp, C):
    """Stage 2: with A and B fixed, fit C = k0 + k1 exp(k2 Cp). k1 and k2 are fitted in log
    space so they stay positive, which makes the map monotonic."""
    k0_init = float(np.min(C)) - 2.0
    slope, icpt = np.polyfit(Cp, np.log(np.maximum(C - k0_init, 1e-6)), 1)
    x0 = np.array([k0_init, icpt, math.log(max(slope, 1e-4))])

    def unpack(x):
        return np.array([x[0], math.exp(x[1]), math.exp(x[2])])

    xs, hist = levenberg_marquardt(lambda x: correction(Cp, unpack(x)) - C, x0)
    k = unpack(xs)
    for h in hist:
        h["k"] = unpack(np.array(h["x"])).tolist()
    return k, hist


def fit_model(I, P, C, cfg):
    A, B, hist_ab, lin = fit_AB(I, P, C, cfg)
    Cp = c_physics(I, P, A, B, cfg)
    k, hist_k = fit_correction(Cp, C)
    return {"A": A, "B": B, "k": k, "hist_ab": hist_ab, "hist_k": hist_k, "lin": lin}


def predict(I, P, model, cfg):
    Cp = c_physics(I, P, model["A"], model["B"], cfg)
    return Cp, correction(Cp, model["k"])


def parameter_statistics(I, P, C, A, B, cfg):
    """Standard errors and the A-B correlation, from J = dC/d(A,B) at the optimum."""
    p, q = basis(I, P, cfg)
    u = A * p + B * q
    J = np.column_stack([100 * np.exp(-u) * p, 100 * np.exp(-u) * q])
    r = 100 * (1 - np.exp(-u)) - C
    dof = max(len(C) - 2, 1)
    s2 = float(r @ r) / dof
    JTJ = J.T @ J
    cov = s2 * np.linalg.inv(JTJ)
    se = np.sqrt(np.diag(cov))
    corr = float(cov[0, 1] / (se[0] * se[1]))
    Js = J * np.array([A, B])            # scale-free Jacobian, for the condition number
    cond = float(np.linalg.cond(Js.T @ Js))
    return {"se_A": float(se[0]), "se_B": float(se[1]), "corr_AB": corr, "cond": cond,
            "ci_A": [A - 1.96 * se[0], A + 1.96 * se[0]], "ci_B": [B - 1.96 * se[1], B + 1.96 * se[1]]}


def calibrate(cfg):
    cfg = {**DEFAULT_CONFIG, **{k: float(v) for k, v in cfg.items() if k in DEFAULT_CONFIG}}
    I, P, C = OBS_I, OBS_P, OBS_C
    model = fit_model(I, P, C, cfg)
    A, B, k = model["A"], model["B"], model["k"]
    C_th = c_physics(I, P, 1.0, 1.0, cfg)
    Cp, Cc = predict(I, P, model, cfg)

    # Validation 1: hold out every 4th pressure row (spread across the whole range)
    test_rows = np.arange(len(P_ROWS))[1::4]
    te = np.isin(OBS_ROW, test_rows)
    tr = ~te
    m_tr = fit_model(I[tr], P[tr], C[tr], cfg)
    vp, vc = predict(I, P, m_tr, cfg)
    holdout = {
        "test_pressures": P_ROWS[test_rows].tolist(),
        "A": m_tr["A"], "B": m_tr["B"], "k": m_tr["k"].tolist(),
        "physics": {"train": metrics(vp[tr], C[tr]), "test": metrics(vp[te], C[te])},
        "corrected": {"train": metrics(vc[tr], C[tr]), "test": metrics(vc[te], C[te])},
    }
    # Validation 2: leave-one-pressure-out cross validation
    lp, lc = np.empty_like(C), np.empty_like(C)
    for r in range(len(P_ROWS)):
        m = OBS_ROW == r
        mm = fit_model(I[~m], P[~m], C[~m], cfg)
        lp[m], lc[m] = predict(I[m], P[m], mm, cfg)
    lopo = {"physics": metrics(lp, C), "corrected": metrics(lc, C)}

    # Loss landscape over (A, B), covering the theory point, the linear estimate and the optimum
    pts_A = [A, 1.0, model["lin"]["A"]] + [h["A"] for h in model["hist_ab"]]
    pts_B = [B, 1.0, model["lin"]["B"]] + [h["B"] for h in model["hist_ab"]]
    gA = np.logspace(math.log10(min(pts_A) / 2.5), math.log10(max(pts_A) * 2.5), 56)
    gB = np.logspace(math.log10(min(pts_B) / 2.5), math.log10(max(pts_B) * 2.5), 56)
    p_, q_ = basis(I, P, cfg)
    U = gA[:, None, None] * p_[None, None, :] + gB[None, :, None] * q_[None, None, :]
    L = np.sum((100 * (1 - np.exp(-U)) - C) ** 2, axis=2)       # L[iA, iB]

    # Smooth curves for the charts
    Pg = np.linspace(P_ROWS.min() * 0.9, P_ROWS.max() * 1.05, 120)
    Dk = knudsen_D(cfg)
    Db = bulk_D(Pg, cfg)
    curves = {"P": Pg.tolist(), "physics": {}, "corrected": {}}
    for c in LEVELS:
        curves["physics"][f"{c:g}"] = current_physics(c, Pg, A, B, cfg).tolist()
        curves["corrected"][f"{c:g}"] = current_physics(correction_inverse(c, k), Pg, A, B, cfg).tolist()
    cp_grid = np.linspace(0, max(60.0, float(Cp.max()) * 1.2), 200)

    return {
        "config": cfg, "source": DATA_SOURCE, "levels": LEVELS.tolist(),
        "data": {"P": P_ROWS.tolist(), "I": I_TABLE.tolist()},
        "obs": {"P": P.tolist(), "I": I.tolist(), "C": C.tolist(), "row": OBS_ROW.tolist(),
                "C_theory": C_th.tolist(), "C_phys": Cp.tolist(), "C_corr": Cc.tolist(),
                "C_lopo_phys": lp.tolist(), "C_lopo_corr": lc.tolist(), "test": te.tolist()},
        "Dk": Dk,
        "theory": {"A": 1.0, "B": 1.0, "metrics": metrics(C_th, C)},
        "physics": {"A": A, "B": B, "metrics": metrics(Cp, C), "lin": model["lin"],
                    "history": model["hist_ab"], **parameter_statistics(I, P, C, A, B, cfg)},
        "corrected": {"k": k.tolist(), "metrics": metrics(Cc, C), "history": model["hist_k"],
                      "curve": {"x": cp_grid.tolist(), "y": correction(cp_grid, k).tolist()}},
        "holdout": holdout, "lopo": lopo,
        "landscape": {"A": gA.tolist(), "B": gB.tolist(), "logloss": np.log10(L).tolist()},
        "curves": curves,
        "diffusion": {"P": Pg.tolist(), "Dk": [Dk] * len(Pg), "Db": Db.tolist(),
                      "Deff_theory": (1 / (1 / Dk + 1 / Db)).tolist(),
                      "Deff": (1 / (A / Dk + B / Db)).tolist(),
                      "knudsen_share": (100 * (A / Dk) / (A / Dk + B / Db)).tolist()},
        "ranges": {"P": [float(P.min()), float(P.max())], "I": [float(I.min()), float(I.max())],
                   "C_phys": [float(Cp.min()), float(Cp.max())], "C": [float(C.min()), float(C.max())]},
    }


STATE = {"cfg": dict(DEFAULT_CONFIG)}
STATE["result"] = calibrate(STATE["cfg"])
_r = STATE["result"]
print("Theory  (A=B=1)      :", {k: round(v, 3) for k, v in _r["theory"]["metrics"].items() if k != "per_level"})
print(f"Physics fit A={_r['physics']['A']:.5g}  B={_r['physics']['B']:.5g}  corr(A,B)={_r['physics']['corr_AB']:.3f}")
print("  metrics            :", {k: round(v, 3) for k, v in _r["physics"]["metrics"].items() if k != "per_level"})
print("Correction k0,k1,k2  :", [round(v, 5) for v in _r["corrected"]["k"]])
print("  metrics            :", {k: round(v, 3) for k, v in _r["corrected"]["metrics"].items() if k != "per_level"})
print(f"Leave-one-pressure-out RMSE: physics {_r['lopo']['physics']['RMSE']:.3f}  corrected {_r['lopo']['corrected']['RMSE']:.3f}")


# ---------- Prediction (stage 2: only P and I are needed) ----------
def predict_point(P, I, state=STATE):
    res, cfg = state["result"], state["cfg"]
    A, B, k = res["physics"]["A"], res["physics"]["B"], np.array(res["corrected"]["k"])
    Cp = float(c_physics(I, P, A, B, cfg))
    Cc = float(correction(Cp, k))
    Dk, Db = knudsen_D(cfg), float(bulk_D(P, cfg))
    rng = res["ranges"]
    warnings = []
    if not rng["P"][0] <= P <= rng["P"][1]:
        warnings.append(f"Pressure is outside the calibrated range {rng['P'][0]:g} to {rng['P'][1]:g}")
    if not rng["C_phys"][0] - 1 <= Cp <= rng["C_phys"][1] + 1:
        warnings.append(f"This (P, I) reading is outside the calibrated band (physics output {Cp:.1f} %), so the result "
                        f"is an extrapolation. The model was calibrated for {rng['C'][0]:g} to {rng['C'][1]:g} % O2")
    Ig = np.linspace(0, max(rng["I"][1] * 1.25, I * 1.1), 160)
    return {
        "P": P, "I": I, "C_phys": Cp, "C_corr": Cc, "C_theory": float(c_physics(I, P, 1, 1, cfg)),
        "Dk": Dk, "Db": Db, "Deff": 1 / (A / Dk + B / Db),
        "knudsen_share": 100 * (A / Dk) / (A / Dk + B / Db),
        "u": float(-math.log(max(1 - Cp / 100, 1e-300))),
        "warnings": warnings,
        "curve": {"I": Ig.tolist(), "phys": c_physics(Ig, P, A, B, cfg).tolist(),
                  "corr": correction(c_physics(Ig, P, A, B, cfg), k).tolist(),
                  "theory": c_physics(Ig, P, 1.0, 1.0, cfg).tolist()},
    }


print("Example: P=56.89, I=8.082 ->", {k: round(v, 3) for k, v in predict_point(56.89, 8.082).items()
                                       if k in ("C_theory", "C_phys", "C_corr")})


