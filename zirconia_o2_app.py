# %% [markdown]
# # Zirconia O2 sensor: physics-based concentration model (single-file version)
#
# Same model as `app.py` + `model.py`, with everything in cells. Input: pressure `P` and current `I`; output: O2 %.
#
# 1. **Physics fit.** `1/Deff = A/Dk + B/Db`, with A and B found by Levenberg-Marquardt on the concentration error.
# 2. **Result correction.** `C = k0 + k1*Cp + k2*Cp^2 + k3*Cp^3` (monotonic cubic, least squares).
# 3. **Outlier screen.** Readings far from all the others (robust MAD rule) are left out of the fit.
#
# Only numpy + flask; no CDN. Run all cells, then open http://127.0.0.1:5050.

# %%
import glob
import math
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.abspath(".")  # notebook folder
# Data file: set the ZIRCONIA_DATA env var to use another workbook. Otherwise the default
# name is used; if that is missing, any .xlsx in this folder; if none, the embedded copy.
DATA_FILE = os.environ.get("ZIRCONIA_DATA",
                           os.path.join(HERE, "zirconia_sensor_complete_experimental_data.xlsx"))

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
    "exclude_outliers": 1.0,   # 1 = leave out readings that disagree strongly with all others, 0 = use every reading
    "outlier_z": 3.5,          # cut-off in robust standard deviations (MAD)
}
NONNEG_KEYS = {"exclude_outliers"}

# Backup copy of the spreadsheet, used if no .xlsx file is found.
FALLBACK_LEVELS = [21, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 95]
FALLBACK_ROWS = [
    [56.89, 8.082, 17.89, 19.78, 21.27, 24.9, 27.35, 31.54, 29.986, 39.96, 45.17, 48.3, 63.51, 59.988, 59.76],
    [62.65, 8.132, 18.88, 20.53, 21.56, 26.3, 28.03, 32.08, 27.301, 41.46, 48.81, 49.74, 64.41, 62.89, 59.88],
    [65.71, 9.011, 19.22, 21.09, 22.56, 26.9, 28.91, 33.4, 27.108, 43.38, 49.24, 51.9, 67.9, 64.85, 67.48],
    [72.76, 9.143, 19.63, 21.16, 23.78, 27.43, 30.44, 35.32, 29.196, 45.76, 50.98, 54.5, 66.64, 69.48, 114.95],
    [78.72, 9.289, 19.9, 22.84, 23.91, 28.8, 31.95, 36.16, 30.587, 46.91, 52.41, 57.8, 64.59, 73.54, 117.89],
    [87.72, 9.801, 20.5, 23.46, 24.45, 29.86, 33.66, 38.45, 31.272, 48.67, 55.96, 60.3, 67.79, 83.76, 121.76],
    [92.18, 8.901, 21.45, 24.47, 25.94, 30.31, 34.7, 39.85, 32.415, 51.33, 58.74, 62.9, 68.61, 87.91, 129.08],
    [106, 9.221, 21.85, 24.99, 26.94, 32.42, 36.38, 40.98, 34.472, 53.63, 60.61, 65.8, 71.98, 91.02, 138.39],
    [116.5, 9.506, 22.26, 25.86, 27.19, 33.45, 37.92, 42.73, 36.046, 54.98, 63.11, 68.73, 74.47, 94.48, 146.001],
    [128.5, 9.612, 22.93, 26.56, 28.88, 35.25, 39.01, 44.23, 37.489, 57.78, 65.91, 71.49, 78.76, 99.61, 154.601],
    [144.2, 10.012, 23.49, 27.4, 29.89, 36.09, 39.96, 45.75, 39.49, 58.67, 68.46, 76.29, 81.33, 129.79, 164.201],
    [155.5, 10.613, 24.05, 27.98, 30.76, 37.16, 41.3, 46.86, 40.577, 60.81, 70.54, 80.59, 85.28, 134.72, 173.018],
    [171.1, 9.879, 24.67, 28.66, 31.56, 37.88, 41.94, 48.49, 41.736, 62.9, 72.29, 82.41, 87.54, 138.58, 179.796],
    [188.3, 9.992, 23.06, 29.37, 32.99, 38.62, 42.63, 48.88, 42.262, 64.24, 74.77, 84.31, 90.2, 141.97, 186.142],
    [207.9, 10.132, 25.49, 29.96, 32.93, 39.45, 43.8, 50.51, 42.992, 65.97, 76.86, 86.41, 93.24, 144.86, 195.697],
    [227.9, 10.161, 26.04, 30.49, 33.8, 40.19, 44.71, 51.47, 45.259, 67.47, 78.49, 88.38, 94.81, 148.55, 200.312],
    [250.5, 10.912, 26.44, 30.91, 34.68, 40.76, 45.69, 52.93, 45.956, 68.25, 80.3, 89.98, 97.45, 151.36, 207.903],
    [273.7, 11.321, 26.76, 30.98, 35.091, 41.37, 46.33, 53.61, 46.94, 69.55, 81.86, 91.86, 99.44, 154.67, 211.759],
    [301.4, 11.541, 27.22, 31.99, 35.04, 41.95, 47.1, 54.69, 47.357, 70.73, 83.23, 93.13, 101.17, 156.14, 218.369],
    [329.8, 11.608, 27.47, 32.33, 36.01, 42.45, 47.74, 55.38, 47.441, 71.55, 84.48, 94.46, 102.63, 158.11, 220.01],
    [360.3, 11.928, 27.88, 32.741, 36.93, 42.92, 48.44, 56.07, 48.593, 72.44, 85.65, 95.55, 112.6, 159.79, 224.734],
    [393.1, 12.021, 28.16, 33.06, 36.53, 43.28, 49.11, 56.72, 49.158, 73.19, 86.57, 96.53, 120.91, 161.27, 227.429],
    [428.1, 12.512, 28.08, 33.26, 36.88, 43.67, 49.47, 57.19, 49.353, 73.85, 87.37, 97.48, 126.35, 162.62, 230.961],
    [465.9, 12.696, 28.1, 33.58, 37.19, 44.02, 49.93, 57.76, 50.777, 74.44, 88.13, 98.45, 130.33, 164.14, 232.285],
    [506.1, 12.88, 28.27, 33.87, 37.49, 44.35, 50.41, 58.25, 50.15, 74.91, 88.93, 99.25, 134.39, 165.19, 234.137],
    [549, 12.94, 28.43, 34.08, 37.73, 44.63, 50.86, 58.68, 51.558, 75.36, 89.63, 99.7, 135.35, 166.21, 236.74],
    [595, 12.993, 28.57, 34.3, 37.93, 45.94, 51.18, 59.09, 51.902, 75.69, 90.3, 99.98, 136.065, 166.98, 238.648],
]

# %%
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
        vals = {}
        for c in row.findall("m:c", ns):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + ord(ch) - 64
            v = c.find("m:v", ns)
            if v is None:
                val = None
            elif c.get("t") == "s":
                val = shared[int(v.text)]
            else:
                try:
                    val = float(v.text)
                except ValueError:
                    val = None
            vals[idx - 1] = val
        width = max(vals) + 1 if vals else 0
        rows.append([vals.get(i) for i in range(width)])
    return rows


def parse_table(raw):
    """Header row: 'Pressure', then one column per concentration, e.g. 'Current at 21% O2 (uA)'."""
    header = raw[0]
    cols, levels = [], []
    for j, h in enumerate(header[1:], start=1):
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(h or ""))
        if not m:
            m = re.fullmatch(r"\s*(0?\.\d+|\d+(?:\.\d+)?)\s*", str(h or ""))   # e.g. 0.21 or 21
        if m:
            v = float(m.group(1))
            levels.append(v * 100 if v <= 1 else v)
            cols.append(j)
    P, I = [], []
    for r in raw[1:]:
        if not r or not isinstance(r[0], float):
            continue
        P.append(r[0])
        I.append([r[j] if j < len(r) and isinstance(r[j], float) else np.nan for j in cols])
    P, I, levels = np.array(P), np.array(I, float), np.array(levels)
    keep = ~np.all(np.isnan(I), axis=0)                 # drop empty columns (e.g. a blank 90 % column)
    return P, I[:, keep], levels[keep]


def find_data_file():
    if os.path.exists(DATA_FILE):
        return DATA_FILE
    files = sorted(glob.glob(os.path.join(HERE, "*.xlsx")), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def load_dataset():
    path = find_data_file()
    if path:
        try:
            P, I, lv = parse_table(read_xlsx_first_sheet(path))
            if len(P) and len(lv):
                return P, I, lv, os.path.abspath(path)
        except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
            pass
    arr = np.array(FALLBACK_ROWS, float)
    return arr[:, 0], arr[:, 1:], np.array(FALLBACK_LEVELS, float), "embedded fallback copy"


P_ROWS, I_TABLE, LEVELS, DATA_SOURCE = load_dataset()
_valid = ~np.isnan(I_TABLE.ravel())
OBS_P = np.repeat(P_ROWS, len(LEVELS))[_valid]
OBS_I = I_TABLE.ravel()[_valid]
OBS_C = np.tile(LEVELS, len(P_ROWS))[_valid]
OBS_ROW = np.repeat(np.arange(len(P_ROWS)), len(LEVELS))[_valid]
print(f"Loaded {len(P_ROWS)} pressures x {len(LEVELS)} concentrations "
      f"({LEVELS.min():g}-{LEVELS.max():g} %) = {len(OBS_C)} readings from {DATA_SOURCE}")

# %%
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
    p1, q1 = basis(1.0, P, cfg)
    with np.errstate(invalid="ignore", divide="ignore"):
        return -np.log(1.0 - np.asarray(C, float) / 100.0) / (A * p1 + B * q1)

# %%
# ---------- Stage 2 correction: monotonic cubic on the physics result ----------
def correction(Cp, corr):
    """C = k0 + k1*Cp + k2*Cp^2 + k3*Cp^3 inside the calibrated band [lo, hi].
    Outside the band it continues as a straight line with the edge slope, so it never turns back.
    The result is clipped to 0-100 %."""
    k, lo, hi = np.asarray(corr["k"]), corr["lo"], corr["hi"]
    Cp = np.asarray(Cp, float)
    dk = np.polyder(k[::-1])[::-1] if len(k) > 1 else np.array([0.0])
    f = lambda x: np.polyval(k[::-1], x)
    df = lambda x: np.polyval(dk[::-1], x)
    out = np.where(Cp < lo, f(lo) + df(lo) * (Cp - lo),
                   np.where(Cp > hi, f(hi) + df(hi) * (Cp - hi), f(Cp)))
    return np.clip(out, 0.0, 100.0)


def correction_inverse(C, corr):
    g = np.linspace(-20, 120, 4001)
    y = correction(g, corr)
    keep = np.concatenate([[True], np.diff(y) > 1e-12])
    return np.interp(np.asarray(C, float), y[keep], g[keep], left=np.nan, right=np.nan)


def fit_correction(Cp, C):
    """Least squares (closed form) for k0..k3. If the cubic is not monotonic over the
    calibrated band, fall back to a quadratic, then a straight line."""
    lo, hi = float(np.min(Cp)), float(np.max(Cp))
    grid = np.linspace(lo, hi, 400)
    for deg in (3, 2, 1):
        V = np.vander(Cp, deg + 1, increasing=True)
        k = np.linalg.lstsq(V, C, rcond=None)[0]
        if np.all(np.diff(np.polyval(k[::-1], grid)) > 0):
            break
    k = np.concatenate([k, np.zeros(4 - len(k))])
    return {"k": k.tolist(), "lo": lo, "hi": hi, "degree": int(deg)}

# %%
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


def levenberg_marquardt(fun, x0, max_iter=300, tol=1e-12):
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
    pred, actual = np.asarray(pred), np.asarray(actual)
    e = pred - actual
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    out = {
        "MAE": float(np.mean(np.abs(e))),
        "RMSE": float(np.sqrt(np.mean(e ** 2))),
        "R2": float(1 - np.sum(e ** 2) / ss_tot) if ss_tot > 0 else float("nan"),
        "MaxAE": float(np.max(np.abs(e))),
        "Bias": float(np.mean(e)),
        "SSE": float(np.sum(e ** 2)),
        "n": int(len(e)),
    }
    out["per_level"] = {f"{c:g}": float(np.mean(np.abs(e[actual == c]))) for c in LEVELS if np.any(actual == c)}
    return out

# %%
# ---------- Calibration ----------
def fit_AB(I, P, C, cfg, start=(1.0, 1.0)):
    """Stage 1: find A, B > 0 minimising sum (C_phys - C_actual)^2.
    1. Linear start: -ln(1 - C/100) = A p + B q is linear in A, B, so ordinary least squares gives a guess.
    2. Levenberg-Marquardt on the real concentration error, over log A and log B (keeps them positive),
       started from the theory point (1, 1) and from the linear guess. The lower loss wins."""
    p, q = basis(I, P, cfg)
    X = -np.log(1.0 - C / 100.0)
    lin = np.maximum(np.linalg.lstsq(np.column_stack([p, q]), X, rcond=None)[0], 1e-12)

    def resid(theta):
        return c_physics(I, P, math.exp(theta[0]), math.exp(theta[1]), cfg) - C

    best = None
    for s in (np.log(start), np.log(lin)):
        th, hist = levenberg_marquardt(resid, s)
        if best is None or hist[-1]["loss"] < best[1][-1]["loss"] - 1e-12:
            best = (th, hist)
    th, hist = best
    for h in hist:
        h["A"], h["B"] = math.exp(h["x"][0]), math.exp(h["x"][1])
    return math.exp(th[0]), math.exp(th[1]), hist, {"A": float(lin[0]), "B": float(lin[1])}


def fit_model(I, P, C, cfg):
    A, B, hist_ab, lin = fit_AB(I, P, C, cfg)
    corr = fit_correction(c_physics(I, P, A, B, cfg), C)
    return {"A": A, "B": B, "corr": corr, "hist_ab": hist_ab, "lin": lin}


def predict(I, P, model, cfg):
    Cp = c_physics(I, P, model["A"], model["B"], cfg)
    return Cp, correction(Cp, model["corr"])


def find_outliers(I, P, C, cfg):
    """Robust screening: fit, measure each reading's error, and drop readings whose error is more than
    outlier_z robust standard deviations (1.4826 * median absolute deviation) from the median.
    Repeat until the set stops changing."""
    used = np.ones(len(C), bool)
    if not cfg["exclude_outliers"]:
        return used, 0.0
    scale = 0.0
    for _ in range(10):
        m = fit_model(I[used], P[used], C[used], cfg)
        res = predict(I, P, m, cfg)[1] - C
        med = np.median(res[used])
        scale = 1.4826 * np.median(np.abs(res[used] - med))
        new = np.abs(res - med) <= cfg["outlier_z"] * scale
        if np.array_equal(new, used):
            break
        used = new
    return used, float(scale)


def parameter_statistics(I, P, C, A, B, cfg):
    """Standard errors and the A-B correlation, from J = dC/d(A,B) at the optimum."""
    p, q = basis(I, P, cfg)
    u = A * p + B * q
    J = np.column_stack([100 * np.exp(-u) * p, 100 * np.exp(-u) * q])
    r = 100 * (1 - np.exp(-u)) - C
    s2 = float(r @ r) / max(len(C) - 2, 1)
    cov = s2 * np.linalg.inv(J.T @ J)
    se = np.sqrt(np.diag(cov))
    Js = J * np.array([A, B])
    return {"se_A": float(se[0]), "se_B": float(se[1]), "corr_AB": float(cov[0, 1] / (se[0] * se[1])),
            "cond": float(np.linalg.cond(Js.T @ Js)),
            "ci_A": [A - 1.96 * se[0], A + 1.96 * se[0]], "ci_B": [B - 1.96 * se[1], B + 1.96 * se[1]]}


def clean_config(cfg):
    out = {**DEFAULT_CONFIG, **{k: float(v) for k, v in (cfg or {}).items() if k in DEFAULT_CONFIG}}
    bad = [k for k, v in out.items() if (v < 0 if k in NONNEG_KEYS else v <= 0)]
    if bad:
        raise ValueError(f"these parameters must be > 0: {', '.join(bad)}")
    return out


def calibrate(cfg):
    cfg = clean_config(cfg)
    I, P, C = OBS_I, OBS_P, OBS_C
    used, scale = find_outliers(I, P, C, cfg)
    Iu, Pu, Cu = I[used], P[used], C[used]

    model = fit_model(Iu, Pu, Cu, cfg)
    A, B, corr = model["A"], model["B"], model["corr"]
    C_th = c_physics(I, P, 1.0, 1.0, cfg)
    Cp, Cc = predict(I, P, model, cfg)

    # Validation 1: hold out every 4th pressure row
    test_rows = np.arange(len(P_ROWS))[1::4]
    te = np.isin(OBS_ROW, test_rows)
    tr_u, te_u = used & ~te, used & te
    m_tr = fit_model(I[tr_u], P[tr_u], C[tr_u], cfg)
    vp, vc = predict(I, P, m_tr, cfg)
    holdout = {
        "test_pressures": P_ROWS[test_rows].tolist(),
        "physics": {"train": metrics(vp[tr_u], C[tr_u]), "test": metrics(vp[te_u], C[te_u])},
        "corrected": {"train": metrics(vc[tr_u], C[tr_u]), "test": metrics(vc[te_u], C[te_u])},
    }
    # Validation 2: leave-one-pressure-out cross validation
    lp, lc = np.full_like(C, np.nan), np.full_like(C, np.nan)
    for r in range(len(P_ROWS)):
        m = OBS_ROW == r
        mm = fit_model(I[used & ~m], P[used & ~m], C[used & ~m], cfg)
        lp[m], lc[m] = predict(I[m], P[m], mm, cfg)
    lopo = {"physics": metrics(lp[used], Cu), "corrected": metrics(lc[used], Cu)}

    # Loss landscape over (A, B)
    pts_A = [A, 1.0, model["lin"]["A"]] + [h["A"] for h in model["hist_ab"]]
    pts_B = [B, 1.0, model["lin"]["B"]] + [h["B"] for h in model["hist_ab"]]
    gA = np.logspace(math.log10(min(pts_A) / 2.5), math.log10(max(pts_A) * 2.5), 56)
    gB = np.logspace(math.log10(min(pts_B) / 2.5), math.log10(max(pts_B) * 2.5), 56)
    p_, q_ = basis(Iu, Pu, cfg)
    U = gA[:, None, None] * p_[None, None, :] + gB[None, :, None] * q_[None, None, :]
    L = np.sum((100 * (1 - np.exp(-U)) - Cu) ** 2, axis=2)

    # Smooth curves for the charts
    Pg = np.linspace(P_ROWS.min() * 0.9, P_ROWS.max() * 1.05, 120)
    Dk, Db = knudsen_D(cfg), bulk_D(Pg, cfg)
    curves = {"P": Pg.tolist(), "physics": {}, "corrected": {}}
    for c in LEVELS:
        curves["physics"][f"{c:g}"] = current_physics(c, Pg, A, B, cfg).tolist()
        cpi = float(correction_inverse(c, corr))
        inside = np.isfinite(cpi) and corr["lo"] - 1 <= cpi <= corr["hi"] + 1     # skip extrapolated levels
        curves["corrected"][f"{c:g}"] = (current_physics(cpi, Pg, A, B, cfg) if inside else np.full_like(Pg, np.nan)).tolist()
    cp_grid = np.linspace(0, 100, 301)
    nan2none = lambda a: [None if not np.isfinite(v) else float(v) for v in np.asarray(a, float)]
    for d in (curves["physics"], curves["corrected"]):
        for key in d:
            d[key] = nan2none(d[key])

    return {
        "config": cfg, "source": DATA_SOURCE, "levels": LEVELS.tolist(),
        "data": {"P": P_ROWS.tolist(), "I": [nan2none(r) for r in I_TABLE]},
        "obs": {"P": P.tolist(), "I": I.tolist(), "C": C.tolist(), "row": OBS_ROW.tolist(),
                "C_theory": C_th.tolist(), "C_phys": Cp.tolist(), "C_corr": Cc.tolist(),
                "C_lopo_phys": nan2none(lp), "C_lopo_corr": nan2none(lc),
                "test": te.tolist(), "used": used.tolist()},
        "outliers": {"enabled": bool(cfg["exclude_outliers"]), "z": cfg["outlier_z"], "scale": scale,
                     "n_excluded": int((~used).sum()), "n_used": int(used.sum()),
                     "by_level": {f"{c:g}": int(np.sum(~used & (C == c))) for c in LEVELS}},
        "Dk": Dk,
        "theory": {"A": 1.0, "B": 1.0, "metrics": metrics(C_th[used], Cu)},
        "physics": {"A": A, "B": B, "metrics": metrics(Cp[used], Cu), "lin": model["lin"],
                    "history": model["hist_ab"], **parameter_statistics(Iu, Pu, Cu, A, B, cfg)},
        "corrected": {"k": corr["k"], "lo": corr["lo"], "hi": corr["hi"], "degree": corr["degree"],
                      "metrics": metrics(Cc[used], Cu),
                      "curve": {"x": cp_grid.tolist(), "y": correction(cp_grid, corr).tolist()}},
        "holdout": holdout, "lopo": lopo,
        "landscape": {"A": gA.tolist(), "B": gB.tolist(), "logloss": np.log10(L).tolist()},
        "curves": curves,
        "diffusion": {"P": Pg.tolist(), "Dk": [Dk] * len(Pg), "Db": Db.tolist(),
                      "Deff_theory": (1 / (1 / Dk + 1 / Db)).tolist(),
                      "Deff": (1 / (A / Dk + B / Db)).tolist(),
                      "knudsen_share": (100 * (A / Dk) / (A / Dk + B / Db)).tolist()},
        "ranges": {"P": [float(P.min()), float(P.max())], "I": [float(I.min()), float(I.max())],
                   "C_phys": [corr["lo"], corr["hi"]], "C": [float(Cu.min()), float(Cu.max())]},
    }


STATE = {"cfg": dict(DEFAULT_CONFIG)}
STATE["result"] = calibrate(STATE["cfg"])
_r = STATE["result"]
_short = lambda m: {k: round(v, 3) for k, v in m.items() if k not in ("per_level",)}
print(f"Outlier screening: {_r['outliers']['n_excluded']} of {len(OBS_C)} readings excluded {_r['outliers']['by_level']}")
print("Theory  (A=B=1)      :", _short(_r["theory"]["metrics"]))
print(f"Physics fit A={_r['physics']['A']:.5g}  B={_r['physics']['B']:.5g}  corr(A,B)={_r['physics']['corr_AB']:.3f}")
print("  metrics            :", _short(_r["physics"]["metrics"]))
print("Correction k0..k3    :", [float(f"{v:.5g}") for v in _r["corrected"]["k"]], "degree", _r["corrected"]["degree"])
print("  metrics            :", _short(_r["corrected"]["metrics"]))
print(f"Leave-one-pressure-out RMSE: physics {_r['lopo']['physics']['RMSE']:.3f}  corrected {_r['lopo']['corrected']['RMSE']:.3f}")

# %%
# ---------- Prediction (only P and I are needed) ----------
def predict_point(P, I, state=STATE):
    res, cfg = state["result"], state["cfg"]
    A, B = res["physics"]["A"], res["physics"]["B"]
    corr = {"k": res["corrected"]["k"], "lo": res["corrected"]["lo"], "hi": res["corrected"]["hi"]}
    Cp = float(c_physics(I, P, A, B, cfg))
    Cc = float(correction(Cp, corr))
    Dk, Db = knudsen_D(cfg), float(bulk_D(P, cfg))
    rng = res["ranges"]
    warnings = []
    if not rng["P"][0] <= P <= rng["P"][1]:
        warnings.append(f"Pressure is outside the calibrated range {rng['P'][0]:g} to {rng['P'][1]:g}")
    if not rng["C_phys"][0] - 1 <= Cp <= rng["C_phys"][1] + 1:
        warnings.append(f"This (P, I) reading is outside the calibrated band (physics output {Cp:.1f} %), so the result "
                        f"is an extrapolation. The model was calibrated for {rng['C'][0]:g} to {rng['C'][1]:g} % O2")
    Ig = np.linspace(0, max(rng["I"][1] * 1.15, I * 1.1), 200)
    cpg = c_physics(Ig, P, A, B, cfg)
    return {
        "P": P, "I": I, "C_phys": Cp, "C_corr": Cc, "C_theory": float(c_physics(I, P, 1, 1, cfg)),
        "Dk": Dk, "Db": Db, "Deff": 1 / (A / Dk + B / Db),
        "knudsen_share": 100 * (A / Dk) / (A / Dk + B / Db),
        "u": float(-math.log(max(1 - Cp / 100, 1e-300))),
        "warnings": warnings,
        "curve": {"I": Ig.tolist(), "phys": cpg.tolist(), "corr": correction(cpg, corr).tolist(),
                  "theory": c_physics(Ig, P, 1.0, 1.0, cfg).tolist()},
    }


if True:
    print("Example: P=56.89, I=8.082 ->", {k: round(v, 3) for k, v in predict_point(56.89, 8.082).items()
                                           if k in ("C_theory", "C_phys", "C_corr")})

# %%
# ---------- Flask app ----------
import threading
from flask import Flask, Response, jsonify, request
app = Flask(__name__)


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.get("/api/results")
def api_results():
    return jsonify(STATE["result"])


@app.get("/api/predict")
def api_predict():
    try:
        P = float(request.args["P"])
        I = float(request.args["I"])
        if P <= 0 or I < 0:
            raise ValueError
    except (KeyError, ValueError):
        return jsonify({"error": "Enter a pressure > 0 and a current >= 0"}), 400
    return jsonify(predict_point(P, I))


@app.post("/api/calibrate")
def api_calibrate():
    body = request.get_json(silent=True) or {}
    try:
        cfg = clean_config(body)
        result = calibrate(cfg)
    except (ValueError, np.linalg.LinAlgError, OverflowError) as exc:
        return jsonify({"error": f"Calibration failed: {exc}"}), 400
    STATE["cfg"], STATE["result"] = cfg, result
    return jsonify(result)


@app.post("/api/reset")
def api_reset():
    STATE["cfg"] = dict(DEFAULT_CONFIG)
    STATE["result"] = calibrate(STATE["cfg"])
    return jsonify(STATE["result"])

# %%
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zirconia O₂ Model</title>
<style>
:root{
  color-scheme: dark;
  --bg:#000; --surface:#0a0a0a; --surface-2:#111; --hover:#161616;
  --border:#1f1f1f; --border-2:#2e2e2e;
  --text:#ededed; --text-2:#a1a1a1; --muted:#6e6e6e;
  --grid:#1a1a1a; --axis:#333;
  --c21:#256abf; --c30:#3987e5; --c35:#6da7ec; --c40:#b7d3f6;
  --phys:#d95926; --corr:#ededed; --theory:#6e6e6e;
  --kn:#3987e5; --bk:#199e70;
  --warn:#fab219; --good:#0ca30c; --crit:#d03b3b;
  --sans: system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:72px}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
a{color:inherit}
.nav{position:sticky;top:0;z-index:20;height:56px;display:flex;align-items:center;gap:24px;padding:0 24px;
  background:rgba(0,0,0,.72);backdrop-filter:saturate(180%) blur(12px);-webkit-backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;letter-spacing:-.01em;white-space:nowrap}
.brand .dot{width:22px;height:22px;border-radius:50%;background:#fff;color:#000;display:grid;place-items:center;font:700 10px var(--sans)}
.brand .sep{color:var(--border-2);font-weight:300}
.brand .sub{color:var(--text-2);font-weight:400}
.nav nav{display:flex;gap:4px;overflow-x:auto}
.nav nav a{color:var(--text-2);text-decoration:none;padding:6px 10px;border-radius:6px;font-size:13px;white-space:nowrap}
.nav nav a:hover{color:var(--text);background:var(--hover)}
.nav .right{margin-left:auto;display:flex;align-items:center;gap:8px}
.pill{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border:1px solid var(--border-2);border-radius:999px;font-size:12px;color:var(--text-2);white-space:nowrap}
.pill i{width:6px;height:6px;border-radius:50%;background:var(--good);display:inline-block}
main{max-width:1240px;margin:0 auto;padding:0 24px 80px}
section{padding:56px 0 8px;border-bottom:1px solid var(--border)}
section:last-of-type{border-bottom:0}
.eyebrow{font:500 12px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:0 0 10px}
h1{font-size:40px;line-height:1.1;letter-spacing:-.035em;margin:0 0 12px;font-weight:700}
h2{font-size:28px;letter-spacing:-.03em;margin:0 0 8px;font-weight:650}
h3{font-size:15px;margin:0;font-weight:600;letter-spacing:-.01em}
.lead{color:var(--text-2);font-size:16px;max-width:760px;margin:0 0 28px}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g-hero{grid-template-columns:minmax(0,5fr) minmax(0,7fr)}
@media (max-width:900px){.g2,.g3,.g-hero{grid-template-columns:1fr}.nav nav{display:none}h1{font-size:30px}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;min-width:0}
.card-h{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:4px}
.card .desc{color:var(--text-2);font-size:13px;margin:2px 0 12px}
label.f{display:block;font-size:13px;color:var(--text-2);margin:0 0 6px}
.field{margin-bottom:16px}
.inp{display:flex;align-items:center;height:44px;background:#000;border:1px solid var(--border-2);border-radius:8px;transition:border-color .15s, box-shadow .15s}
.inp:focus-within{border-color:#888;box-shadow:0 0 0 3px rgba(255,255,255,.08)}
.inp input,.inp select{flex:1;min-width:0;height:100%;background:transparent;border:0;outline:0;color:var(--text);font:500 16px var(--mono);padding:0 12px}
.inp select{font:14px var(--sans);appearance:none;cursor:pointer}
.inp select option{background:#111}
.inp .unit{padding:0 12px;color:var(--muted);font:13px var(--mono);border-left:1px solid var(--border);height:100%;display:flex;align-items:center}
.btn{height:36px;padding:0 14px;border-radius:8px;border:1px solid var(--border-2);background:#000;color:var(--text);font:500 13px var(--sans);cursor:pointer;transition:background .15s,border-color .15s}
.btn:hover{background:var(--hover);border-color:#444}
.btn.primary{background:#ededed;color:#000;border-color:#ededed}
.btn.primary:hover{background:#fff}
.btn:disabled{opacity:.5;cursor:wait}
.seg{display:inline-flex;border:1px solid var(--border-2);border-radius:8px;padding:2px;gap:2px;background:#000}
.seg button{height:28px;padding:0 10px;border:0;border-radius:6px;background:transparent;color:var(--text-2);font:500 12px var(--sans);cursor:pointer}
.seg button.on{background:#1f1f1f;color:var(--text)}
.result{display:flex;flex-direction:column;justify-content:space-between}
.big{font:700 72px/1 var(--sans);letter-spacing:-.05em;margin:8px 0 4px}
.big small{font-size:28px;color:var(--text-2);font-weight:500;margin-left:4px;letter-spacing:-.02em}
.kv{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;border-top:1px solid var(--border);margin-top:18px}
.kv div{padding:12px 12px 4px 0}
.kv dt{font-size:12px;color:var(--muted);margin:0}
.kv dd{margin:2px 0 0;font:500 14px var(--mono);font-variant-numeric:tabular-nums}
.warn{display:flex;gap:8px;align-items:flex-start;margin-top:14px;padding:10px 12px;border:1px solid #4a3a10;background:#1a1405;border-radius:8px;color:#f5d48a;font-size:13px}
.warn b{color:var(--warn)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0;border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:16px;background:var(--surface)}
.tile{padding:18px 20px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);margin:0 -1px -1px 0}
.tile .t{font-size:12px;color:var(--muted)}
.tile .v{font:600 26px var(--sans);letter-spacing:-.03em;margin-top:6px}
.tile .s{font:12px var(--mono);color:var(--text-2);margin-top:2px}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;overflow:visible}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--text-2);margin:0 0 8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend svg{width:18px;height:12px;overflow:visible}
.tip{position:absolute;pointer-events:none;z-index:5;background:#111;border:1px solid var(--border-2);border-radius:8px;padding:8px 10px;font:12px/1.5 var(--mono);color:var(--text);white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.6);opacity:0;transition:opacity .08s}
.tip .n{font-family:var(--sans);color:var(--text-2);font-size:11px}
.eq{font:14px/1.7 var(--mono);background:#000;border:1px solid var(--border);border-radius:8px;padding:12px 14px;overflow-x:auto;white-space:nowrap;color:#e6e6e6;margin:10px 0}
.eq .hl{color:#fff;background:#1f1f1f;border-radius:4px;padding:1px 4px}
.steps{counter-reset:s;list-style:none;padding:0;margin:0}
.steps li{position:relative;padding:0 0 18px 44px;color:var(--text-2)}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;border:1px solid var(--border-2);display:grid;place-items:center;font:600 12px var(--mono);color:var(--text)}
.steps li:after{content:"";position:absolute;left:13px;top:30px;bottom:4px;width:1px;background:var(--border)}
.steps li:last-child:after{display:none}
.steps b{color:var(--text);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 12px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-weight:500;color:var(--muted);font-size:12px;background:var(--surface)}
td{font-family:var(--mono);font-variant-numeric:tabular-nums}
td.l{font-family:var(--sans)}
tbody tr:hover td{background:var(--hover)}
.tbl{border:1px solid var(--border);border-radius:12px;overflow:auto;max-height:520px;background:var(--surface)}
.tbl thead th{position:sticky;top:0}
.good{color:#4ade80}.bad{color:#f87171}.dim{color:var(--muted)}
.note{color:var(--text-2);font-size:13px}
.params{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:4px 16px}
.params .inp{height:38px}.params .inp input{font-size:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:middle;margin-right:6px}
code{font:12.5px var(--mono);background:#161616;border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:#e6e6e6}
.toast{position:fixed;bottom:20px;right:20px;background:#111;border:1px solid var(--border-2);border-radius:8px;padding:10px 14px;font-size:13px;opacity:0;transform:translateY(8px);transition:all .2s;z-index:50}
.toast.on{opacity:1;transform:none}
footer{max-width:1240px;margin:0 auto;padding:24px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
.loading{color:var(--muted);padding:80px 0;text-align:center}
</style>
</head>
<body>
<header class="nav">
  <div class="brand"><span class="dot">O₂</span>Zirconia<span class="sep">/</span><span class="sub">Physics model</span></div>
  <nav>
    <a href="#predict">Predict</a><a href="#calibration">Calibration</a><a href="#optimization">Optimization</a>
    <a href="#validation">Validation</a><a href="#parameters">Parameters</a><a href="#data">Data</a>
  </nav>
  <div class="right"><span class="pill" id="status"><i></i>Loading…</span></div>
</header>

<main id="app">
  <div class="loading">Calibrating model…</div>
</main>
<footer>Physics-based inverse model · modified Bosanquet diffusion <span style="font-family:var(--mono)">1/Deff = A/Dk + B/Db</span> · runs fully offline (Flask + numpy, no CDN)</footer>
<div class="toast" id="toast"></div>

<script>
"use strict";
/* ---------------- helpers ---------------- */
const $ = s => document.querySelector(s);
// Concentration is ordinal, so levels get one blue hue from dark (low %) to light (high %),
// plus a repeating marker shape as a second cue. Built from the levels in the data.
let LV_HEX = {}, LV_SHAPE = {};
const LV_STOPS = ["#256abf","#3987e5","#6da7ec","#9ec5f4","#cde2fb"];
function setupLevels(levels){
  LV_HEX = {}; LV_SHAPE = {};
  const shapes = ["circle","square","triangle","diamond"], n = levels.length;
  levels.forEach((c,i) => { const t = n > 1 ? i/(n-1) : 0, s = t*(LV_STOPS.length-1), j = Math.min(Math.floor(s), LV_STOPS.length-2);
    LV_HEX[String(c)] = lerpHex(LV_STOPS[j], LV_STOPS[j+1], s-j); LV_SHAPE[String(c)] = shapes[i % 4]; });
}
const EXCL = "#8a8a8a";
const COL = {phys:"#d95926", corr:"#ededed", theory:"#6e6e6e", kn:"#3987e5", bk:"#199e70"};
let R = null, PRED = null, MODEL = "corr";

function fmt(v, d=3){
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(Math.max(d-1,1));
  return (+v.toFixed(d)).toLocaleString("en-US",{maximumFractionDigits:d, minimumFractionDigits:0});
}
const fx = (v,d=2) => (v===null||!isFinite(v)) ? "—" : Number(v).toFixed(d);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("on"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("on"),2600); }
async function api(url, opts){ const r = await fetch(url, opts); const j = await r.json(); if(!r.ok) throw new Error(j.error||r.statusText); return j; }

/* ---------------- tiny SVG chart library ---------------- */
function niceTicks(min, max, n=5){
  if (min === max){ min -= 1; max += 1; }
  const raw = (max-min)/n, mag = Math.pow(10, Math.floor(Math.log10(raw))), e = raw/mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(min/step - 1e-9)*step; v <= max + step*1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
function logTicks(min, max){
  const out = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++){
    for (const m of [1,2,5]){ const v = m*Math.pow(10,e); if (v >= min*0.999 && v <= max*1.001) out.push(v); }
  }
  return out.length >= 2 ? out : [min, max];
}
function shapePath(shape, x, y, r){
  switch(shape){
    case "square":   return `M${x-r*.88},${y-r*.88}h${r*1.76}v${r*1.76}h${-r*1.76}z`;
    case "triangle": return `M${x},${y-r*1.15}L${x+r*1.05},${y+r*.75}L${x-r*1.05},${y+r*.75}z`;
    case "diamond":  return `M${x},${y-r*1.2}L${x+r*1.2},${y}L${x},${y+r*1.2}L${x-r*1.2},${y}z`;
    default:         return `M${x-r},${y}a${r},${r} 0 1,0 ${2*r},0a${r},${r} 0 1,0 ${-2*r},0`;
  }
}
function legendHTML(items){
  return `<div class="legend">${items.map(s => {
    const sym = s.type === "line"
      ? `<svg viewBox="0 0 18 12"><line x1="1" y1="6" x2="17" y2="6" stroke="${s.color}" stroke-width="2" ${s.dash?`stroke-dasharray="${s.dash}"`:""} stroke-linecap="round"/></svg>`
      : `<svg viewBox="0 0 18 12"><path d="${shapePath(s.shape||"circle",9,6,4)}" ${s.hollow?`fill="none" stroke="${s.color}" stroke-width="1.5"`:`fill="${s.color}"`}/></svg>`;
    return `<span>${sym}${esc(s.name)}</span>`;
  }).join("")}</div>`;
}
const CHARTS = new Map();
function plot(el, o){
  CHARTS.set(el, () => plot(el, o));
  const W = Math.max(el.clientWidth || 600, 260), H = o.height || 280;
  const m = {l:o.y.log ? 64 : 56, r:16, t:10, b:42};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const all = [];
  for (const s of o.series) if (!s.noExtent) for (const p of s.pts) if (Number.isFinite(p[0]) && Number.isFinite(p[1])) all.push(p);
  const ext = (k, ax) => {
    let lo = ax.min ?? Math.min(...all.map(p=>p[k])), hi = ax.max ?? Math.max(...all.map(p=>p[k]));
    if (!ax.log && ax.min === undefined && ax.max === undefined){ const pad=(hi-lo)*0.06||1; lo-=pad; hi+=pad; }
    if (ax.log){ lo = ax.min ?? lo/1.15; hi = ax.max ?? hi*1.15; }
    return [lo, hi];
  };
  const [x0,x1] = ext(0, o.x), [y0,y1] = ext(1, o.y);
  const sc = (lo, hi, log, a, b) => log
    ? v => a + (Math.log10(v)-Math.log10(lo))/(Math.log10(hi)-Math.log10(lo))*(b-a)
    : v => a + (v-lo)/(hi-lo)*(b-a);
  const X = sc(x0,x1,o.x.log,m.l,m.l+iw), Y = sc(y0,y1,o.y.log,m.t+ih,m.t);
  const xt = o.x.log ? logTicks(x0,x1) : niceTicks(x0,x1,o.x.ticks||6).filter(v=>v>=x0&&v<=x1);
  const yt = o.y.log ? logTicks(y0,y1) : niceTicks(y0,y1,o.y.ticks||5).filter(v=>v>=y0&&v<=y1);
  const logFmt = v => { const a = Math.abs(v); return (a < 1e-3 || a >= 1e5) ? v.toExponential(0).replace("e-","e−") : fmt(v,3); };
  const tf = o.x.fmt || (o.x.log ? logFmt : v=>fmt(v,3)), tfy = o.y.fmt || (o.y.log ? logFmt : v=>fmt(v,3));
  let g = `<defs><clipPath id="cp${el.id}"><rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/></clipPath></defs>`;
  for (const v of yt) g += `<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/>
    <text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${tfy(v)}</text>`;
  for (const v of xt) g += `<line y1="${m.t}" y2="${m.t+ih}" x1="${X(v)}" x2="${X(v)}" stroke="var(--grid)"/>
    <text x="${X(v)}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${tf(v)}</text>`;
  g += `<line x1="${m.l}" x2="${m.l+iw}" y1="${m.t+ih}" y2="${m.t+ih}" stroke="var(--axis)"/>`;
  g += `<text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.x.label||"")}</text>`;
  g += `<text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.y.label||"")}</text>`;
  let body = "";
  for (const b of (o.bands||[])){
    const ya = Y(Math.min(Math.max(b.y1,y0),y1)), yb = Y(Math.max(Math.min(b.y0,y1),y0));
    body += `<rect x="${m.l}" width="${iw}" y="${ya}" height="${Math.max(yb-ya,0)}" fill="#fff" fill-opacity=".035"/>
      <text x="${m.l+iw-6}" y="${ya+14}" text-anchor="end" fill="var(--muted)" font-size="11">${esc(b.label||"")}</text>`;
  }
  for (const s of o.series.filter(s=>s.type==="line")){
    let d = "", pen = false;
    for (const p of s.pts){
      if (!Number.isFinite(p[0])||!Number.isFinite(p[1])||(o.y.log&&p[1]<=0)){ pen=false; continue; }
      d += (pen?"L":"M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1); pen = true;
    }
    body += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width||2}" stroke-linejoin="round" stroke-linecap="round" ${s.dash?`stroke-dasharray="${s.dash}"`:""} ${s.opacity?`stroke-opacity="${s.opacity}"`:""}/>`;
  }
  for (const s of o.series.filter(s=>s.type!=="line")){
    for (const p of s.pts){
      if (!Number.isFinite(p[0])||!Number.isFinite(p[1])) continue;
      body += s.hollow
        ? `<path d="${shapePath(s.shape||"circle", X(p[0]), Y(p[1]), s.r||4)}" fill="none" stroke="${s.color}" stroke-width="1.5"/>`
        : `<path d="${shapePath(s.shape||"circle", X(p[0]), Y(p[1]), s.r||4)}" fill="${s.color}" stroke="var(--surface)" stroke-width="1.5" ${s.opacity?`fill-opacity="${s.opacity}"`:""}/>`;
    }
  }
  if (o.marker){
    const mx = X(o.marker.x), my = Y(o.marker.y);
    if (isFinite(mx) && isFinite(my)) body += `
      <line x1="${mx}" x2="${mx}" y1="${m.t}" y2="${m.t+ih}" stroke="#fff" stroke-opacity=".35" stroke-dasharray="3 3"/>
      <line x1="${m.l}" x2="${m.l+iw}" y1="${my}" y2="${my}" stroke="#fff" stroke-opacity=".35" stroke-dasharray="3 3"/>
      <circle cx="${mx}" cy="${my}" r="7" fill="none" stroke="#fff" stroke-width="2"/>
      <circle cx="${mx}" cy="${my}" r="2.5" fill="#fff"/>
      <text x="${Math.min(mx+11, m.l+iw-4)}" y="${Math.max(my-10, m.t+12)}" text-anchor="${mx > m.l+iw-120 ? "end":"start"}" fill="#fff" font-size="12" font-weight="600">${esc(o.marker.label||"")}</text>`;
  }
  const leg = o.legend === false ? "" : legendHTML(o.series.filter(s=>s.name && !s.hideLegend));
  el.innerHTML = `${leg}<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.aria||o.y.label||"chart")}">
    ${g}<g clip-path="url(#cp${el.id})">${body}</g><g class="hl"></g>
    <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/></svg><div class="tip"></div></div>`;
  // hover layer: nearest point (pixel distance)
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), hl = el.querySelector(".hl");
  const pts = [];
  for (const s of o.series){ if (s.noHover) continue;
    for (const p of s.pts) if (Number.isFinite(p[0])&&Number.isFinite(p[1])) pts.push({px:X(p[0]),py:Y(p[1]),p,s}); }
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W / r.width;
    const mx = (ev.clientX - r.left)*k, my = (ev.clientY - r.top)*k;
    let best = null, bd = 1e9;
    for (const q of pts){ const d = (q.px-mx)**2 + (q.py-my)**2; if (d < bd){ bd = d; best = q; } }
    if (!best || bd > 40*40){ tip.style.opacity = 0; hl.innerHTML = ""; return; }
    hl.innerHTML = `<circle cx="${best.px}" cy="${best.py}" r="6.5" fill="none" stroke="#fff" stroke-width="1.5"/>`;
    const lines = o.tip ? o.tip(best.p, best.s) : [`${o.x.label}: ${fmt(best.p[0],4)}`, `${o.y.label}: ${fmt(best.p[1],4)}`];
    tip.innerHTML = `<div class="n">${esc(best.s.name||"")}</div>` + lines.map(esc).join("<br>");
    tip.style.opacity = 1;
    const tx = best.px / k, ty = best.py / k + (leg ? el.querySelector(".legend").offsetHeight + 8 : 0);
    tip.style.left = Math.min(tx + 14, r.width - tip.offsetWidth - 4) + "px";
    tip.style.top = Math.max(ty - tip.offsetHeight - 10, 0) + "px";
    tip.parentElement.style.position = "relative";
  });
  svg.addEventListener("mouseleave", () => { tip.style.opacity = 0; hl.innerHTML = ""; });
}

/* heatmap for the loss landscape (log axes on A and B) */
function lerpHex(a, b, t){ const p = h => [1,3,5].map(i => parseInt(h.slice(i,i+2),16)); const A=p(a),B=p(b);
  return "#" + A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,"0")).join(""); }
const RAMP = ["#0b1a33","#104281","#1c5cab","#3987e5","#86b6ef","#cde2fb"]; // high loss (dark) -> low loss (bright)
function rampColor(t){ t = Math.min(Math.max(t,0),1); const s = t*(RAMP.length-1), i = Math.min(Math.floor(s), RAMP.length-2); return lerpHex(RAMP[i], RAMP[i+1], s-i); }
function heatmap(el, o){
  CHARTS.set(el, () => heatmap(el, o));
  const W = Math.max(el.clientWidth || 600, 260), H = o.height || 320, m = {l:60,r:16,t:10,b:42};
  const iw = W-m.l-m.r, ih = H-m.t-m.b, xs = o.xv, ys = o.yv, Z = o.z;
  const lx0 = Math.log10(xs[0]), lx1 = Math.log10(xs[xs.length-1]), ly0 = Math.log10(ys[0]), ly1 = Math.log10(ys[ys.length-1]);
  const X = v => m.l + (Math.log10(v)-lx0)/(lx1-lx0)*iw, Y = v => m.t + ih - (Math.log10(v)-ly0)/(ly1-ly0)*ih;
  let zmin = Infinity, zmax = -Infinity; for (const r of Z) for (const v of r){ zmin=Math.min(zmin,v); zmax=Math.max(zmax,v); }
  const cw = iw/xs.length, ch = ih/ys.length;
  let cells = "";
  for (let i=0;i<xs.length;i++) for (let j=0;j<ys.length;j++){
    const t = 1 - (Z[i][j]-zmin)/(zmax-zmin);
    cells += `<rect x="${(m.l+i*cw).toFixed(1)}" y="${(m.t+ih-(j+1)*ch).toFixed(1)}" width="${(cw+0.6).toFixed(1)}" height="${(ch+0.6).toFixed(1)}" fill="${rampColor(t*t)}"/>`;
  }
  let axes = "";
  for (const v of logTicks(xs[0], xs[xs.length-1])) axes += `<line x1="${X(v)}" x2="${X(v)}" y1="${m.t+ih}" y2="${m.t+ih+4}" stroke="var(--axis)"/><text x="${X(v)}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,3)}</text>`;
  for (const v of logTicks(ys[0], ys[ys.length-1])) axes += `<line x1="${m.l-4}" x2="${m.l}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--axis)"/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,3)}</text>`;
  axes += `<text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.xlabel)}</text>
    <text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.ylabel)}</text>`;
  const path = o.path.map((p,i)=>(i?"L":"M")+X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)).join("");
  let marks = `<path d="${path}" fill="none" stroke="${COL.phys}" stroke-width="2" stroke-linejoin="round"/>`;
  o.path.forEach((p,i)=> marks += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${i?3.5:4.5}" fill="${COL.phys}" stroke="#000" stroke-width="1.5"/>`);
  for (const p of o.points){
    const px = X(p.x), py = Y(p.y);
    marks += `<path d="${shapePath(p.shape||"circle",px,py,p.r||5)}" fill="${p.fill||"#fff"}" stroke="#000" stroke-width="2"/>
      <text x="${px + (p.dx??10)}" y="${py + (p.dy??-8)}" text-anchor="${p.anchor||"start"}" fill="#fff" font-size="12" font-weight="600" paint-order="stroke" stroke="#000" stroke-width="3">${esc(p.label)}</text>`;
  }
  const gradStops = RAMP.map((c,i)=>`<stop offset="${i/(RAMP.length-1)}" stop-color="${c}"/>`).join("");
  el.innerHTML = `<div class="legend"><span><svg viewBox="0 0 18 12"><line x1="1" y1="6" x2="17" y2="6" stroke="${COL.phys}" stroke-width="2"/></svg>Levenberg–Marquardt path</span>
      <span><svg viewBox="0 0 60 12" style="width:60px"><defs><linearGradient id="lg${el.id}">${gradStops}</linearGradient></defs><rect x="0" y="2" width="60" height="8" rx="2" fill="url(#lg${el.id})"/></svg>log₁₀ SSE: high → low (bright = better fit)</span></div>
    <div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Loss landscape over A and B">${cells}${axes}${marks}
    <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg><div class="tip"></div></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W/r.width, mx = (ev.clientX-r.left)*k, my = (ev.clientY-r.top)*k;
    const i = Math.floor((mx-m.l)/cw), j = Math.floor((m.t+ih-my)/ch);
    if (i<0||j<0||i>=xs.length||j>=ys.length){ tip.style.opacity=0; return; }
    tip.innerHTML = `<div class="n">Loss surface</div>A = ${fmt(xs[i],4)}<br>B = ${fmt(ys[j],4)}<br>SSE = ${fmt(Math.pow(10,Z[i][j]),4)}`;
    tip.style.opacity = 1;
    tip.style.left = Math.min(mx/k+14, r.width-tip.offsetWidth-4)+"px";
    tip.style.top = Math.max(my/k + el.querySelector(".legend").offsetHeight - tip.offsetHeight + 0, 0)+"px";
  });
  svg.addEventListener("mouseleave", ()=> tip.style.opacity=0);
}

/* grouped bars (MAE per concentration level per model) */
function bars(el, o){
  CHARTS.set(el, () => bars(el, o));
  const W = Math.max(el.clientWidth||600, 260), H = o.height||280, m = {l:56,r:16,t:10,b:42};
  const iw = W-m.l-m.r, ih = H-m.t-m.b;
  const ymax = Math.max(...o.groups.flatMap(g=>g.values)) * 1.12;
  const yt = niceTicks(0, ymax, 5).filter(v=>v<=ymax);
  const Y = v => m.t + ih - v/ymax*ih;
  const gw = iw/o.groups.length, n = o.series.length, gap = 2, bw = Math.min(28, (gw*0.7 - gap*(n-1))/n);
  let s = "";
  for (const v of yt) s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${m.l-8}" y="${Y(v)+4}" text-anchor="end" fill="var(--muted)" font-size="11" font-family="var(--mono)">${fmt(v,2)}</text>`;
  const rects = [];
  o.groups.forEach((g, gi) => {
    const cx = m.l + gw*gi + gw/2, start = cx - (n*bw + (n-1)*gap)/2;
    g.values.forEach((v, si) => {
      const x = start + si*(bw+gap), y = Y(v), h = m.t+ih-y, rr = Math.min(4, h, bw/2);
      s += `<path d="M${x},${m.t+ih}V${y+rr}Q${x},${y} ${x+rr},${y}H${x+bw-rr}Q${x+bw},${y} ${x+bw},${y+rr}V${m.t+ih}Z" fill="${o.series[si].color}"/>`;
      rects.push({x, y, w:bw, h, v, g:g.label, s:o.series[si].name});
    });
    s += `<text x="${cx}" y="${m.t+ih+17}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="var(--mono)">${esc(g.label)}</text>`;
  });
  s += `<line x1="${m.l}" x2="${m.l+iw}" y1="${m.t+ih}" y2="${m.t+ih}" stroke="var(--axis)"/>
    <text x="${m.l+iw/2}" y="${H-4}" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.xlabel)}</text>
    <text transform="translate(13,${m.t+ih/2}) rotate(-90)" text-anchor="middle" fill="var(--text-2)" font-size="12">${esc(o.ylabel)}</text>`;
  el.innerHTML = legendHTML(o.series.map(x=>({...x,type:"bar",shape:"square"}))) + `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.ylabel)}">${s}</svg><div class="tip"></div></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), k = W/r.width, mx=(ev.clientX-r.left)*k, my=(ev.clientY-r.top)*k;
    const b = rects.find(b => mx >= b.x-1 && mx <= b.x+b.w+1 && my >= Math.min(b.y, m.t+ih-12) - 2 && my <= m.t+ih);
    if (!b){ tip.style.opacity=0; return; }
    tip.innerHTML = `<div class="n">${esc(b.s)}</div>${esc(b.g)} O₂ · MAE ${fmt(b.v,3)} %`;
    tip.style.opacity=1; tip.style.left = Math.min(b.x/k+b.w/k+8, r.width-tip.offsetWidth-4)+"px";
    tip.style.top = Math.max(b.y/k + el.querySelector(".legend").offsetHeight - 20, 0)+"px";
  });
  svg.addEventListener("mouseleave", ()=> tip.style.opacity=0);
}

let rsz; window.addEventListener("resize", () => { clearTimeout(rsz); rsz = setTimeout(() => CHARTS.forEach(f => f()), 120); });

/* ---------------- page ---------------- */
function card(id, title, desc, h){ return `<div class="card"><div class="card-h"><h3>${title}</h3></div><p class="desc">${desc}</p><div id="${id}" style="min-height:${h||280}px"></div></div>`; }

function render(){
  const r = R, ph = r.physics, co = r.corrected, th = r.theory, k = co.k, cfg = r.config, ol = r.outliers;
  setupLevels(r.levels);
  const lvTxt = `${r.levels[0]}–${r.levels[r.levels.length-1]} %`;
  const sgn = v => v < 0 ? "− " + fmt(-v,4) : "+ " + fmt(v,4);
  const corrEq = `${fmt(k[0],4)} ${sgn(k[1])}·Cp ${sgn(k[2])}·Cp² ${sgn(k[3])}·Cp³`;
  const exclTxt = Object.entries(ol.by_level).filter(([c,n])=>n>0).map(([c,n])=>`${n} at ${c} %`).join(", ");
  const pct = (a,b) => (100*(1-b/a)).toFixed(0);
  $("#status").innerHTML = `<i></i>Calibrated · RMSE ${fx(co.metrics.RMSE,2)} %`;
  const opts = r.obs.P.map((p,i)=>`<option value="${i}">P ${p} · I ${r.obs.I[i]} µA · actual ${r.obs.C[i]} %${r.obs.used[i]?"":" (excluded)"}</option>`).join("");
  const worst = Object.entries(ph.metrics.per_level).sort((a,b)=>b[1]-a[1])[0];
  $("#app").innerHTML = `
  <section id="predict">
    <p class="eyebrow">Stage 2 · Prediction</p>
    <h1>Oxygen concentration from pressure and current.</h1>
    <p class="lead">Enter a pressure and the measured zirconia sensor current. The calibrated physics model inverts
      <span style="font-family:var(--mono)">I = −(4FSP·Deff / RTL)·ln(1 − C/100)</span> with the optimized A and B, then applies the result correction.</p>
    <div class="grid g-hero">
      <div class="card">
        <div class="field"><label class="f" for="inP">Pressure P</label>
          <div class="inp"><input id="inP" type="number" step="any" min="0" value="56.89" inputmode="decimal"><span class="unit">kPa</span></div></div>
        <div class="field"><label class="f" for="inI">Sensor current I</label>
          <div class="inp"><input id="inI" type="number" step="any" min="0" value="8.082" inputmode="decimal"><span class="unit">µA</span></div></div>
        <div class="field"><label class="f" for="inEx">Or load a calibration reading</label>
          <div class="inp"><select id="inEx"><option value="">Choose a measured point…</option>${opts}</select><span class="unit">▾</span></div></div>
        <div class="row" style="justify-content:space-between;margin-top:6px">
          <div class="seg" id="segModel"><button data-m="corr" class="on">Physics + correction</button><button data-m="phys">Physics only (A, B)</button></div>
          <button class="btn primary" id="btnPredict">Predict</button>
        </div>
      </div>
      <div class="card result">
        <div>
          <div class="card-h"><h3>Predicted O₂ concentration</h3><span class="pill" id="modelPill">physics + correction</span></div>
          <div class="big" id="outC">—</div>
          <div class="note" id="outSub"></div>
          <div id="outWarn"></div>
        </div>
        <dl class="kv" id="outKV"></dl>
      </div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card("chPredCurve","Concentration vs current at this pressure","Every model's C(I) curve at the entered pressure. The ring marks your reading. The shaded band is the calibrated range, and the dotted part of the white curve is extrapolation outside it.")}
      ${card("chMap","Where the reading sits on the calibration map","Measured calibration currents (points) and the calibrated iso-concentration curves (lines). Levels where the correction would extrapolate have no line. Your reading is the ring.")}
    </div>
  </section>

  <section id="calibration">
    <p class="eyebrow">Stage 1 · Calibration</p>
    <h2>Optimized coefficients</h2>
    <p class="lead">${r.data.P.length} pressures × ${r.levels.length} concentrations (${lvTxt}) = ${r.obs.C.length} readings.
      ${ol.enabled ? `The outlier screen left out <b style="color:var(--text)">${ol.n_excluded}</b> readings (${exclTxt || "none"}), so the fit uses ${ol.n_used}. Excluded points are drawn as hollow grey markers.` : "Every reading is used (outlier screen off)."}
      Data: <code>${esc(r.source)}</code></p>
    <div class="tiles">
      <div class="tile"><div class="t">A · Knudsen correction</div><div class="v">${fmt(ph.A,4)}</div><div class="s">± ${fmt(ph.se_A,3)} (1σ)</div></div>
      <div class="tile"><div class="t">B · bulk correction</div><div class="v">${fmt(ph.B,4)}</div><div class="s">± ${fmt(ph.se_B,3)} (1σ)</div></div>
      <div class="tile"><div class="t">Correction k₀ · k₁ · k₂ · k₃</div><div class="v" style="font-size:14px;margin-top:10px;font-family:var(--mono)">${fmt(k[0],3)} · ${fmt(k[1],3)}<br>${fmt(k[2],3)} · ${fmt(k[3],3)}</div><div class="s">cubic in C_phys</div></div>
      <div class="tile"><div class="t">RMSE · theory A=B=1</div><div class="v">${fx(th.metrics.RMSE,2)} %</div><div class="s">R² ${fx(th.metrics.R2,3)}</div></div>
      <div class="tile"><div class="t">RMSE · physics fit</div><div class="v">${fx(ph.metrics.RMSE,2)} %</div><div class="s">R² ${fx(ph.metrics.R2,3)} · −${pct(th.metrics.RMSE,ph.metrics.RMSE)}%</div></div>
      <div class="tile"><div class="t">RMSE · physics + correction</div><div class="v">${fx(co.metrics.RMSE,2)} %</div><div class="s">R² ${fx(co.metrics.R2,3)} · −${pct(th.metrics.RMSE,co.metrics.RMSE)}%</div></div>
    </div>
    <div class="grid g2">
      ${card("chParity","Actual vs predicted","Each column is one known concentration, with the models offset slightly so they don't overlap. On the 45° line, the prediction equals the actual value.")}
      ${card("chLevel","Mean absolute error per concentration",`How each model performs at each concentration (${lvTxt}). Only readings used in the fit.`)}
      ${card("chResPhys","Residuals vs pressure · physics only (A, B)","Predicted − actual. A and B alone cannot match every concentration at once: the low concentrations show a clear bias.")}
      ${card("chResCorr","Residuals vs pressure · physics + correction","The same residuals after the correction, on the same y-scale.")}
      ${card("chCorrMap","Result correction: physics output → concentration","x is the concentration predicted by the A,B physics model and y is the true concentration. The white curve is the fitted map, the dashed line is identity.")}
      ${card("chIP","Sensor current vs pressure · data and model","Points are measured. Solid lines are the calibrated model (physics + correction). Dashed lines are physics only.")}
    </div>
  </section>

  <section id="optimization">
    <p class="eyebrow">Method</p>
    <h2>How A and B are optimized</h2>
    <p class="lead">A and B rescale the Knudsen and bulk diffusion resistances. They are found by minimizing the squared concentration error over the whole dataset.</p>
    <div class="grid g2">
      <div class="card">
        <ol class="steps">
          <li><b>Physics terms per observation.</b> For each (P, I) the code computes Dk = (2a/3)·√(8RT/πM) and Db = D0·(T/273)^α·(P0/P). The inverse model can then be written as
            <div class="eq">C = 100·[1 − exp(−(<span class="hl">A</span>·p + <span class="hl">B</span>·q))]<br>p = I·RTL/(4FSP·Dk) &nbsp; q = I·RTL/(4FSP·Db)</div></li>
          <li><b>Linear starting point.</b> Because −ln(1 − C/100) = A·p + B·q is linear in A and B, ordinary least squares gives a closed-form first estimate:
            A = ${fmt(ph.lin.A,4)}, B = ${fmt(ph.lin.B,4)}.</li>
          <li><b>Levenberg–Marquardt refinement.</b> The real objective is in concentration space:
            <div class="eq">Loss(A,B) = Σᵢ [C_pred(Pᵢ, Iᵢ; A, B) − C_actual,ᵢ]²</div>
            LM is a blend of Gauss–Newton and gradient descent. Each step solves (JᵀJ + λ·diag JᵀJ)·Δ = −Jᵀr. The search runs over log A and log B, so both stay positive. It starts from the theory point (1, 1) and from the linear estimate, and keeps the lower loss.
            It converged in ${ph.history.length-1} iterations: SSE ${fmt(ph.history[0].loss,4)} → ${fmt(ph.history[ph.history.length-1].loss,4)}.</li>
          <li><b>Identifiability check.</b> From the Jacobian at the optimum: corr(A, B) = ${fx(ph.corr_AB,3)}, condition number ${fmt(ph.cond,3)}.
            ${Math.abs(ph.corr_AB) < 0.95 ? "Both coefficients can be identified separately," : "A and B are strongly correlated,"} because the data spans the pressure range where the Knudsen share of resistance moves from
            ${fx(Math.max(...r.diffusion.knudsen_share),0)} % to ${fx(Math.min(...r.diffusion.knudsen_share),0)} % (see the chart below).</li>
          <li><b>Why A and B alone are not enough.</b> At a fixed pressure the physics says I ∝ −ln(1 − C/100). The measured currents follow that law well in the middle of the range, but not at every concentration (the 21 % current is lower than the law predicts). A and B only rescale the curve at each pressure, so they cannot bend its shape. The largest remaining error is at ${worst[0]} % (MAE ${fx(worst[1],2)} %).</li>
          <li><b>Correction applied to the result.</b> With A and B fixed, the physics output is mapped through
            <div class="eq">C = <span class="hl">k₀</span> + <span class="hl">k₁</span>·Cp + <span class="hl">k₂</span>·Cp² + <span class="hl">k₃</span>·Cp³<br>&nbsp; = ${corrEq}</div>
            Cp is the physics result. The k values are found by ordinary least squares, which has an exact one-step solution. The code checks that the curve only goes up across the calibrated band (Cp ${fx(co.lo,1)}–${fx(co.hi,1)} %); if not, it drops to a quadratic, then a straight line. Outside the band it continues as a straight line, so a higher current always means a higher concentration. Degree used: ${co.degree}. RMSE drops from ${fx(ph.metrics.RMSE,2)} % to ${fx(co.metrics.RMSE,2)} %.</li>
          <li><b>Outlier screen.</b> ${ol.enabled ? `The model is fitted, and any reading whose error is more than ${fmt(ol.z,2)} robust standard deviations (1.4826 × median absolute deviation = ${fx(ol.scale,2)} %) from the median is left out. This repeats until nothing changes. ${ol.n_excluded} readings were excluded: ${exclTxt || "none"}. You can switch this off in Parameters.` : "Switched off: every reading is used."}</li>
        </ol>
      </div>
      <div class="grid" style="gap:16px">
        ${card("chLand","Loss landscape over A and B","SSE on a log grid of A and B. Orange is the Levenberg–Marquardt path from the theory point (1, 1). The white point is the optimum and the square is the linear OLS start.",320)}
        ${card("chConv","Convergence","Stage 1 (A, B): sum of squared concentration errors at each accepted iteration. Stage 2 has an exact one-step solution, so it has no iterations.",220)}
      </div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card("chDiff","Diffusion coefficients vs pressure","Dk is independent of pressure. Db falls as 1/P. The effective coefficient follows Bosanquet, both as theory (A=B=1) and as fitted.")}
      ${card("chShare","Share of diffusion resistance","Knudsen term A/Dk vs bulk term B/Db as a fraction of 1/Deff. The share changes across the measured pressures, which is what makes A and B separately identifiable.")}
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div><h3 style="margin:0 0 10px">Stage 1 iterations · A, B</h3><div class="tbl" style="max-height:300px"><table>
        <thead><tr><th>Iter</th><th>A</th><th>B</th><th>SSE</th><th>RMSE %</th><th>λ</th></tr></thead>
        <tbody>${ph.history.map(h=>`<tr><td>${h.it}</td><td>${fmt(h.A,6)}</td><td>${fmt(h.B,6)}</td><td>${fmt(h.loss,5)}</td><td>${fx(Math.sqrt(h.loss/ol.n_used),4)}</td><td>${h.lam.toExponential(1)}</td></tr>`).join("")}</tbody></table></div></div>
      <div><h3 style="margin:0 0 10px">Parameter statistics</h3><div class="tbl"><table style="font-size:12px">
        <thead><tr><th>Parameter</th><th>Estimate</th><th>Std. error</th><th>95 % CI</th></tr></thead>
        <tbody>
          <tr><td class="l">A (Knudsen)</td><td>${fmt(ph.A,5)}</td><td>${fmt(ph.se_A,4)}</td><td>${fmt(ph.ci_A[0],4)} … ${fmt(ph.ci_A[1],4)}</td></tr>
          <tr><td class="l">B (bulk)</td><td>${fmt(ph.B,5)}</td><td>${fmt(ph.se_B,4)}</td><td>${fmt(ph.ci_B[0],4)} … ${fmt(ph.ci_B[1],4)}</td></tr>
          <tr><td class="l">corr(A, B)</td><td>${fx(ph.corr_AB,4)}</td><td class="dim">—</td><td class="dim">${Math.abs(ph.corr_AB)<0.95?"identifiable":"weakly identifiable"}</td></tr>
          <tr><td class="l">k₀ · k₁ · k₂ · k₃</td><td>${k.map(v=>fmt(v,3)).join(" · ")}</td><td class="dim">—</td><td class="dim">deg ${co.degree}</td></tr>
          <tr><td class="l">Dk (constant)</td><td>${fmt(r.Dk,4)}</td><td class="dim">m²/s</td><td class="dim">—</td></tr>
        </tbody></table></div>
        <p class="note">A and B are relative to the geometry in <a href="#parameters">Parameters</a>. If you change a, S or L, A and B rescale to compensate, and the predicted concentrations stay the same. Enter the real sensor specs if you want A and B to have physical meaning.</p></div>
    </div>
  </section>

  <section id="validation">
    <p class="eyebrow">Generalization</p>
    <h2>Validation</h2>
    <p class="lead">Two checks on data the model did not see. (1) Hold-out: every 4th pressure (${r.holdout.test_pressures.map(v=>fmt(v,2)).join(", ")}) is removed, the model is refitted, and it is tested on those rows. (2) Leave-one-pressure-out: ${r.data.P.length} refits, each predicting the pressure it left out. Errors are measured on the ${ol.n_used} readings used in the fit.</p>
    <div class="tbl" style="max-height:none"><table>
      <thead><tr><th>Model</th><th>Fit on all · RMSE</th><th>Fit on all · MAE</th><th>Fit on all · R²</th><th>Hold-out train RMSE</th><th>Hold-out test RMSE</th><th>LOPO-CV RMSE</th><th>LOPO-CV MAE</th><th>Max |error|</th></tr></thead>
      <tbody>
        <tr><td class="l"><span class="sw" style="background:${COL.theory}"></span>Theory (A = B = 1)</td><td>${fx(th.metrics.RMSE,3)}</td><td>${fx(th.metrics.MAE,3)}</td><td>${fx(th.metrics.R2,4)}</td><td class="dim">—</td><td class="dim">—</td><td class="dim">—</td><td class="dim">—</td><td>${fx(th.metrics.MaxAE,2)}</td></tr>
        <tr><td class="l"><span class="sw" style="background:${COL.phys}"></span>Physics fit (A, B)</td><td>${fx(ph.metrics.RMSE,3)}</td><td>${fx(ph.metrics.MAE,3)}</td><td>${fx(ph.metrics.R2,4)}</td><td>${fx(r.holdout.physics.train.RMSE,3)}</td><td>${fx(r.holdout.physics.test.RMSE,3)}</td><td>${fx(r.lopo.physics.RMSE,3)}</td><td>${fx(r.lopo.physics.MAE,3)}</td><td>${fx(ph.metrics.MaxAE,2)}</td></tr>
        <tr><td class="l"><span class="sw" style="background:${COL.corr}"></span>Physics + correction</td><td>${fx(co.metrics.RMSE,3)}</td><td>${fx(co.metrics.MAE,3)}</td><td>${fx(co.metrics.R2,4)}</td><td>${fx(r.holdout.corrected.train.RMSE,3)}</td><td>${fx(r.holdout.corrected.test.RMSE,3)}</td><td>${fx(r.lopo.corrected.RMSE,3)}</td><td>${fx(r.lopo.corrected.MAE,3)}</td><td>${fx(co.metrics.MaxAE,2)}</td></tr>
      </tbody></table></div>
    <p class="note" style="margin-top:12px">All values are in % O₂. The cross-validated error is close to the fitted error, so the model is not overfitting. An exact 0 error is not possible with this data, because some readings go against the trend (sudden steps or dips within a column). The spreadsheet notes flag several handwritten values as uncertain, so check them against the original notebook. Use the model inside the calibrated range: P ${r.ranges.P[0]}–${r.ranges.P[1]} and C ${r.ranges.C[0]}–${r.ranges.C[1]} %.</p>
  </section>

  <section id="parameters">
    <p class="eyebrow">Configuration</p>
    <h2>Sensor &amp; operating parameters</h2>
    <p class="lead">Change these to match your sensor and click Recalibrate. A, B and the correction are refitted on the same experimental data.</p>
    <div class="card">
      <div class="params" id="params"></div>
      <div class="row" style="margin-top:8px"><button class="btn primary" id="btnCal">Recalibrate</button><button class="btn" id="btnReset">Reset defaults</button><span class="note" id="calMsg"></span></div>
    </div>
  </section>

  <section id="data">
    <p class="eyebrow">Table view</p>
    <h2>Experimental data &amp; predictions</h2>
    <p class="lead">Every reading with its prediction from the physics-only model and from physics + correction. Error is the corrected prediction minus the actual value.</p>
    <div class="tbl"><table>
      <thead><tr><th>Pressure</th><th>Actual O₂ %</th><th>Current µA</th><th>Theory %</th><th>C_phys %</th><th>C_final %</th><th>Error %</th><th>Status</th></tr></thead>
      <tbody>${r.obs.P.map((p,i)=>{const e=r.obs.C_corr[i]-r.obs.C[i], u=r.obs.used[i];
        return `<tr${u?"":' style="opacity:.55"'}><td>${p}${r.obs.test[i]?' <span class="dim">·test</span>':""}</td><td>${r.obs.C[i]}</td><td>${r.obs.I[i]}</td><td class="dim">${fx(r.obs.C_theory[i],2)}</td><td class="dim">${fx(r.obs.C_phys[i],2)}</td><td>${fx(r.obs.C_corr[i],2)}</td><td class="${Math.abs(e)<1?"good":Math.abs(e)>3?"bad":""}">${e>=0?"+":""}${fx(e,2)}</td><td class="l">${u?"used":"excluded"}</td></tr>`}).join("")}</tbody>
    </table></div>
  </section>`;

  // parameters form
  const PDEF = [["T","Temperature T","K"],["a","Pore radius a","m"],["S","Cross-section S","m²"],["L","Thickness L","m"],
    ["M","O₂ molar mass M","kg/mol"],["D0","Reference diffusivity D0","m²/s"],["alpha","Temperature exponent α","—"],
    ["P0","Reference pressure P0","data unit"],["P_to_Pa","Pressure unit → Pa","×"],["I_to_A","Current unit → A","×"],
    ["exclude_outliers","Exclude outliers (1 = yes, 0 = no)","0/1"],["outlier_z","Outlier cut-off","× MAD"]];
  $("#params").innerHTML = PDEF.map(([k,l,u])=>`<div class="field"><label class="f" for="cfg_${k}">${l}</label><div class="inp"><input id="cfg_${k}" data-k="${k}" type="number" step="any" value="${cfg[k]}"><span class="unit">${u}</span></div></div>`).join("");
  $("#btnCal").onclick = () => recalibrate("/api/calibrate", Object.fromEntries([...document.querySelectorAll("#params input")].map(i=>[i.dataset.k, i.value])));
  $("#btnReset").onclick = () => recalibrate("/api/reset", {});

  // predictor wiring
  let tmr;
  const go = () => { clearTimeout(tmr); tmr = setTimeout(doPredict, 140); };
  $("#inP").addEventListener("input", go); $("#inI").addEventListener("input", go);
  $("#btnPredict").onclick = doPredict;
  $("#inEx").onchange = e => { const i = e.target.value; if (i === "") return; $("#inP").value = r.obs.P[i]; $("#inI").value = r.obs.I[i]; doPredict(); };
  document.querySelectorAll("#segModel button").forEach(b => b.onclick = () => {
    MODEL = b.dataset.m; document.querySelectorAll("#segModel button").forEach(x=>x.classList.toggle("on", x===b)); showPrediction(); });

  drawCalibrationCharts();
  doPredict();
}

function drawCalibrationCharts(){
  const r = R, o = r.obs, L = r.levels.map(String);
  const byLevel = (fn, extra={}) => {
    const s = L.map(c => ({name:`${c} %`, color:LV_HEX[c], shape:LV_SHAPE[c], type:"scatter", r:3.5,
      pts:o.P.map((p,i)=>i).filter(i=>String(o.C[i])===c && o.used[i]).map(fn), ...extra}));
    const ex = o.P.map((p,i)=>i).filter(i=>!o.used[i]);
    if (ex.length) s.push({name:"excluded", color:EXCL, shape:"circle", hollow:true, type:"scatter", r:4, pts:ex.map(i=>[...fn(i).slice(0,2), ...fn(i).slice(2), `${o.C[i]} % (excluded)`])});
    return s;
  };

  // parity (models dodged horizontally)
  const dodge = {theory:-0.9, phys:0, corr:0.9};
  const ser = (key, name, arr, color) => ({name, color, type:"scatter", r:3, opacity:.9, pts:o.C.map((c,i)=>[c+dodge[key], arr[i], c, o.P[i], o.I[i]]).filter((q,i)=>o.used[i])});
  plot($("#chParity"), {x:{label:"Actual O₂ (%)", min:r.ranges.C[0]-4, max:r.ranges.C[1]+4}, y:{label:"Predicted O₂ (%)"},
    series:[{name:"45° reference", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[0,0],[100,100]]},
      ser("theory","Theory A=B=1",o.C_theory,COL.theory), ser("phys","Physics (A, B)",o.C_phys,COL.phys), ser("corr","Physics + correction",o.C_corr,COL.corr)],
    tip:(p,s)=>[`actual ${p[2]} % · predicted ${fx(p[1],2)} %`, `error ${fx(p[1]-p[2],2)} %`, `P ${p[3]} · I ${p[4]} µA`]});

  bars($("#chLevel"), {xlabel:"Actual O₂ concentration (%)", ylabel:"MAE (% O₂)",
    series:[{name:"Theory A=B=1",color:COL.theory},{name:"Physics (A, B)",color:COL.phys},{name:"Physics + correction",color:COL.corr}],
    groups:L.filter(c=>r.corrected.metrics.per_level[c] !== undefined).map(c=>({label:c, values:[r.theory.metrics.per_level[c], r.physics.metrics.per_level[c], r.corrected.metrics.per_level[c]]}))});

  const allRes = o.C.flatMap((c,i)=> o.used[i] ? [o.C_phys[i]-c, o.C_corr[i]-c] : []);
  const ylim = Math.ceil(Math.max(...allRes.map(Math.abs))) + 0.5;
  const resTip = (p)=>[`P ${p[0]} · residual ${fx(p[1],3)} %`, `I ${p[2]} µA`];
  const zero = {name:"", type:"line", color:"#555", width:1, noHover:true, noExtent:true, hideLegend:true, pts:[[0,0],[1e4,0]]};
  plot($("#chResPhys"), {x:{label:"Pressure"}, y:{label:"Predicted − actual (% O₂)", min:-ylim, max:ylim}, tip:resTip,
    series:[zero, ...byLevel(i=>[o.P[i], o.C_phys[i]-o.C[i], o.I[i]])]});
  plot($("#chResCorr"), {x:{label:"Pressure"}, y:{label:"Predicted − actual (% O₂)", min:-ylim, max:ylim}, tip:resTip,
    series:[zero, ...byLevel(i=>[o.P[i], o.C_corr[i]-o.C[i], o.I[i]])]});

  plot($("#chCorrMap"), {x:{label:"Physics output C_phys (%)"}, y:{label:"Actual / corrected O₂ (%)"},
    series:[{name:"identity", type:"line", color:"#555", dash:"4 4", width:1.5, noHover:true, noExtent:true, pts:[[0,0],[100,100]]},
      {name:"fitted cubic map", type:"line", color:COL.corr, pts:r.corrected.curve.x.map((x,i)=>[x, r.corrected.curve.y[i]]).filter(p=>p[0]>=r.ranges.C_phys[0]-4 && p[0]<=r.ranges.C_phys[1]+4)},
      ...byLevel(i=>[o.C_phys[i], o.C[i], o.P[i], o.C_corr[i]])],
    tip:(p,s)=> p.length>2 ? [`C_phys ${fx(p[0],2)} % → corrected ${fx(p[3],2)} %`, `actual ${p[1]} % · P ${p[2]}`] : [`C_phys ${fx(p[0],2)} → ${fx(p[1],2)} %`]});

  const cv = r.curves;
  plot($("#chIP"), {x:{label:"Pressure"}, y:{label:"Sensor current (µA)"},
    series:[...L.map(c=>({name:`${c} % physics only`, type:"line", color:LV_HEX[c], dash:"3 4", width:1.5, opacity:.7, hideLegend:true, pts:cv.P.map((p,i)=>[p, cv.physics[c][i]])})),
      ...L.map(c=>({name:`${c} % model`, type:"line", color:LV_HEX[c], hideLegend:true, pts:cv.P.map((p,i)=>[p, cv.corrected[c][i]])})),
      ...byLevel(i=>[o.P[i], o.I[i], o.C[i]])],
    tip:(p,s)=>[`P ${fmt(p[0],4)} · I ${fx(p[1],3)} µA`]});

  // landscape
  const ph = r.physics, Ls = r.landscape;
  heatmap($("#chLand"), {xv:Ls.A, yv:Ls.B, z:Ls.logloss, xlabel:"A (Knudsen coefficient, log)", ylabel:"B (bulk coefficient, log)", height:320,
    path: ph.history.map(h=>[h.A,h.B]),
    points:[{x:1,y:1,label:"theory (1, 1)",fill:COL.theory, shape:"diamond"},
      {x:ph.lin.A,y:ph.lin.B,label:"OLS start",fill:"#86b6ef",shape:"square",dy:18},
      {x:ph.A,y:ph.B,label:`A*=${fmt(ph.A,3)}, B*=${fmt(ph.B,3)}`,fill:"#fff",r:5.5, anchor:"end", dx:-10}]});

  const allLoss = ph.history.map(h=>h.loss);
  plot($("#chConv"), {height:220, x:{label:"Iteration", min:0, max:Math.max(ph.history.length-1, 1), fmt:v=>fmt(v,0)}, y:{label:"SSE (%²)", log:true, min:Math.min(...allLoss, R.corrected.metrics.SSE)/1.5, max:Math.max(...allLoss)*1.5},
    series:[{name:"Stage 1 · A, B", type:"line", color:COL.phys, pts:ph.history.map(h=>[h.it,h.loss])},
      {name:"", type:"scatter", color:COL.phys, r:3.5, hideLegend:true, pts:ph.history.map(h=>[h.it,h.loss])},
      {name:"", type:"line", color:COL.corr, dash:"4 4", width:1.5, noHover:true, hideLegend:true, pts:[[0, R.corrected.metrics.SSE],[Math.max(ph.history.length-1,1), R.corrected.metrics.SSE]]},
      {name:"Stage 2 result (one step)", type:"scatter", color:COL.corr, r:3.5, pts:[[Math.max(ph.history.length-1,1), R.corrected.metrics.SSE]]}],
    tip:(p,s)=>[`iteration ${p[0]}`, `SSE ${fmt(p[1],5)}`, `RMSE ${fx(Math.sqrt(p[1]/R.outliers.n_used),3)} %`]});

  const d = r.diffusion;
  plot($("#chDiff"), {x:{label:"Pressure"}, y:{label:"Diffusion coefficient (m²/s)", log:true},
    series:[{name:"Dk Knudsen", type:"line", color:COL.kn, pts:d.P.map((p,i)=>[p,d.Dk[i]])},
      {name:"Db bulk", type:"line", color:COL.bk, pts:d.P.map((p,i)=>[p,d.Db[i]])},
      {name:"Deff theory (A=B=1)", type:"line", color:COL.theory, dash:"5 4", pts:d.P.map((p,i)=>[p,d.Deff_theory[i]])},
      {name:"Deff fitted (A*, B*)", type:"line", color:COL.corr, pts:d.P.map((p,i)=>[p,d.Deff[i]])}],
    tip:(p,s)=>[`P ${fmt(p[0],4)}`, `${fmt(p[1],4)} m²/s`]});
  plot($("#chShare"), {x:{label:"Pressure"}, y:{label:"Share of 1/Deff (%)", min:0, max:100},
    series:[{name:"Knudsen A/Dk", type:"line", color:COL.kn, pts:d.P.map((p,i)=>[p,d.knudsen_share[i]])},
      {name:"Bulk B/Db", type:"line", color:COL.bk, pts:d.P.map((p,i)=>[p,100-d.knudsen_share[i]])}],
    tip:(p,s)=>[`P ${fmt(p[0],4)}`, `${s.name}: ${fx(p[1],1)} %`]});
}

async function doPredict(){
  const P = parseFloat($("#inP").value), I = parseFloat($("#inI").value);
  if (!(P > 0) || !(I >= 0)){ $("#outC").innerHTML = "—"; $("#outSub").textContent = "Enter a pressure > 0 and a current ≥ 0."; return; }
  try { PRED = await api(`/api/predict?P=${encodeURIComponent(P)}&I=${encodeURIComponent(I)}`); showPrediction(); }
  catch(e){ $("#outSub").textContent = e.message; }
}

function showPrediction(){
  const p = PRED, r = R; if (!p) return;
  const C = MODEL === "corr" ? p.C_corr : p.C_phys;
  $("#outC").innerHTML = `${fx(C,2)}<small>% O₂</small>`;
  $("#modelPill").textContent = MODEL === "corr" ? "physics + correction" : "physics only · A, B";
  const ex = r.obs.P.findIndex((pp,i)=> Math.abs(pp-p.P)<1e-9 && Math.abs(r.obs.I[i]-p.I)<1e-9);
  $("#outSub").innerHTML = ex >= 0
    ? `Calibration reading, known value <b style="color:var(--text)">${r.obs.C[ex]} %</b> · error ${C-r.obs.C[ex]>=0?"+":""}${fx(C-r.obs.C[ex],2)} %`
    : `From P = ${fmt(p.P,4)} and I = ${fmt(p.I,4)} µA`;
  $("#outWarn").innerHTML = p.warnings.map(w=>`<div class="warn"><b>⚠</b><span>${esc(w)}</span></div>`).join("");
  $("#outKV").innerHTML = [
    ["Physics + correction", fx(p.C_corr,3)+" %"], ["Physics only (A, B)", fx(p.C_phys,3)+" %"], ["Theory (A=B=1)", fx(p.C_theory,3)+" %"],
    ["Dk", fmt(p.Dk,4)+" m²/s"], ["Db(T,P)", fmt(p.Db,4)+" m²/s"], ["Deff", fmt(p.Deff,4)+" m²/s"],
    ["Knudsen share", fx(p.knudsen_share,1)+" %"], ["Exponent u", fmt(p.u,4)], ["A · B", `${fmt(r.physics.A,4)} · ${fmt(r.physics.B,4)}`]
  ].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");

  const cv = p.curve, inBand = c => c >= r.ranges.C_phys[0]-1 && c <= r.ranges.C_phys[1]+1;
  plot($("#chPredCurve"), {x:{label:"Sensor current I (µA)", min:0, max:cv.I[cv.I.length-1]}, y:{label:"O₂ concentration (%)", min:0, max:100},
    bands:[{y0:r.ranges.C[0], y1:r.ranges.C[1], label:"calibrated range"}],
    series:[{name:"Theory A=B=1", type:"line", color:COL.theory, dash:"5 4", pts:cv.I.map((x,i)=>[x,cv.theory[i]])},
      {name:"Physics (A, B)", type:"line", color:COL.phys, pts:cv.I.map((x,i)=>[x,cv.phys[i]])},
      {name:"Physics + correction", type:"line", color:COL.corr, pts:cv.I.map((x,i)=>inBand(cv.phys[i]) ? [x,cv.corr[i]] : [x,NaN])},
      {name:"Correction, extrapolated", type:"line", color:COL.corr, dash:"2 4", width:1.5, opacity:.6, pts:cv.I.map((x,i)=>inBand(cv.phys[i]) ? [x,NaN] : [x,cv.corr[i]])}],
    marker:{x:p.I, y:C, label:`${fx(C,2)} %`},
    tip:(q,s)=>[`I ${fx(q[0],3)} µA → ${fx(q[1],2)} %`]});

  const o = r.obs, L = r.levels.map(String), cvv = r.curves;
  plot($("#chMap"), {x:{label:"Pressure"}, y:{label:"Sensor current (µA)"},
    series:[...L.map(c=>({name:`${c} %`, type:"line", color:LV_HEX[c], hideLegend:true, pts:cvv.P.map((pp,i)=>[pp, cvv.corrected[c][i]])})),
      ...L.map(c=>({name:`${c} %`, color:LV_HEX[c], shape:LV_SHAPE[c], type:"scatter", r:3,
        pts:o.P.map((pp,i)=>[pp,o.I[i],o.C[i],o.used[i]]).filter(q=>String(q[2])===c && q[3])})),
      {name:"excluded", color:EXCL, shape:"circle", hollow:true, type:"scatter", r:3.5, pts:o.P.map((pp,i)=>[pp,o.I[i],o.C[i],o.used[i]]).filter(q=>!q[3])}],
    marker:{x:p.P, y:p.I, label:`your reading · ${fx(C,1)} %`},
    tip:(q,s)=>[`P ${fmt(q[0],4)} · I ${fx(q[1],3)} µA`]});
}

async function recalibrate(url, body){
  const b1 = $("#btnCal"), b2 = $("#btnReset"); b1.disabled = b2.disabled = true; $("#calMsg").textContent = "Calibrating…";
  try {
    const keepP = $("#inP").value, keepI = $("#inI").value;
    R = await api(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    render(); $("#inP").value = keepP; $("#inI").value = keepI; doPredict();
    toast(`Recalibrated · A=${fmt(R.physics.A,4)}, B=${fmt(R.physics.B,4)}, RMSE ${fx(R.corrected.metrics.RMSE,2)} %`);
    location.hash = "#parameters";
  } catch(e){ $("#calMsg").textContent = e.message; b1.disabled = b2.disabled = false; }
}

api("/api/results").then(j => { R = j; render(); }).catch(e => { $("#app").innerHTML = `<div class="loading">Failed to load: ${esc(e.message)}</div>`; });
</script>
</body>
</html>
"""

# %%
# ---------- Run the server (works inside Jupyter; re-running this cell restarts it) ----------
HOST, PORT = "127.0.0.1", 5050


def _in_notebook():
    try:
        return get_ipython().__class__.__name__ == "ZMQInteractiveShell"  # noqa: F821
    except NameError:
        return False


def start_server(host=HOST, port=PORT):
    from werkzeug.serving import make_server
    stop_server()
    srv = make_server(host, port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    globals()["_SERVER"] = srv
    print(f"Zirconia O2 model UI running at http://{host}:{port}   (call stop_server() to stop)")
    return srv


def stop_server():
    srv = globals().get("_SERVER")
    if srv is not None:
        srv.shutdown()
        srv.server_close()
        globals()["_SERVER"] = None


if _in_notebook():
    start_server()
elif __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
