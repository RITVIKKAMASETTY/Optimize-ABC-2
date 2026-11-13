"""Physics model, A/B optimizer and calibration for the zirconia O2 sensor.

Stage 1  physics:     1/Deff = A/Dk + B/Db, with A and B found by Levenberg-Marquardt on the C error
Stage 2  correction:  C = k0 + k1*Cp + k2*Cp^2 + k3*Cp^3, a monotonic cubic applied to the physics result
"""
import glob
import math
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
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


if __name__ == "__main__":
    print("Example: P=56.89, I=8.082 ->", {k: round(v, 3) for k, v in predict_point(56.89, 8.082).items()
                                           if k in ("C_theory", "C_phys", "C_corr")})
