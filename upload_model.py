"""Upload workflow: Excel/CSV -> pick columns -> filter rows -> I = V / R -> fit A, B four ways -> average.

Model (same physics as before, no extra correction):
    C = 100 * [1 - exp(-(I R T L / 4 F S P) * (A/Dk + B/Db))]
    Dk = (2a/3) sqrt(8RT / (pi M))            Knudsen diffusion
    Db = D0 (T/273)^alpha (P0/P)             bulk diffusion

Four fitting conditions:
    1. Optimize A, B = 1
    2. Optimize B, A = 1
    3. Optimize A and B together
    4. A = B = K, optimize K   (K/Deff = 1/Dk + 1/Db, i.e. one factor on the whole Bosanquet sum)
Final model: A_avg = mean of A over the 4 conditions, B_avg = mean of B over the 4 conditions.
"""
import csv
import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

F_CONST = 96485.33212       # C/mol
R_CONST = 8.314462618       # J/(mol K)

# Sensor constants (placeholders; replace with the real sensor values).
DEFAULT_CONSTANTS = {
    "T_fixed": 973.15,    # K, used when no temperature column is chosen
    "a": 5.0e-7,          # m, pore radius
    "S": 1.0e-10,         # m^2, diffusion cross-section
    "L": 1.0e-3,          # m, diffusion barrier thickness
    "M": 0.031998,        # kg/mol, O2 molar mass
    "D0": 1.8e-5,         # m^2/s, O2 bulk diffusivity at 273 K and P0
    "alpha": 1.75,        # temperature exponent
    "P0": 101325.0,       # Pa, reference pressure of D0
}

UNITS = {
    "voltage": {"V": 1.0, "mV": 1e-3, "uV": 1e-6},
    "resistance": {"ohm": 1.0, "kohm": 1e3, "Mohm": 1e6},
    "pressure": {"Pa": 1.0, "kPa": 1e3, "bar": 1e5, "mbar": 100.0, "atm": 101325.0,
                 "psi": 6894.757, "Torr": 133.322},
    "concentration": {"%": 1.0, "fraction": 100.0, "ppm": 1e-4},
    "temperature": {"C": "C", "K": "K"},
}

OPS = {">": np.greater, ">=": np.greater_equal, "<": np.less, "<=": np.less_equal,
       "=": np.isclose, "!=": lambda a, b: ~np.isclose(a, b)}


# ---------------------------------------------------------------- reading files
def _col_index(ref):
    col = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_sheets(data):
    """Return [(sheet name, path inside the zip)]."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for s in wb.find("m:sheets", ns):
        t = target.get(s.get(f"{{{ns['r']}}}id"), "")
        t = t.lstrip("/")
        out.append((s.get("name"), t if t.startswith("xl/") else "xl/" + t))
    return out


def read_xlsx(data, sheet=None):
    """Read one sheet into a list of rows (strings or floats). Standard library only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheets = xlsx_sheets(data)
    path = dict(sheets).get(sheet, sheets[0][1]) if sheets else "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        root = ET.fromstring(z.read(path))
    rows = []
    for row in root.find("m:sheetData", ns).findall("m:row", ns):
        vals = {}
        for c in row.findall("m:c", ns):
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            elif v is None:
                val = None
            elif t == "s":
                val = shared[int(v.text)]
            elif t in ("str", "e"):
                val = v.text
            elif t == "b":
                val = float(v.text)
            else:
                try:
                    val = float(v.text)
                except (TypeError, ValueError):
                    val = v.text
            vals[_col_index(c.get("r"))] = val
        rownum = int(row.get("r", len(rows) + 1))
        while len(rows) < rownum - 1:          # keep empty rows so row numbers match Excel
            rows.append([])
        rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
    return rows


def read_csv(data):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


def load_file(filename, data, sheet=None):
    """Returns {'rows': raw rows, 'sheets': [...], 'sheet': name}."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        sheets = [s for s, _ in xlsx_sheets(data)]
        sheet = sheet if sheet in sheets else sheets[0]
        return {"rows": read_xlsx(data, sheet), "sheets": sheets, "sheet": sheet}
    if name.endswith((".csv", ".txt", ".tsv")):
        return {"rows": read_csv(data), "sheets": [], "sheet": None}
    if name.endswith(".xls"):
        raise ValueError("Old .xls files are not supported. Save the file as .xlsx or .csv in Excel and upload again.")
    raise ValueError("Upload an .xlsx or .csv file.")


def to_float(v):
    if v is None:
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("−", "-")
    if not s:
        return np.nan
    if s.count(",") == 1 and "." not in s:      # decimal comma, e.g. 12,5
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def table(rows, header_row=1):
    """Split raw rows into column names and data rows. header_row is 1-based."""
    h = max(1, int(header_row))
    if len(rows) < h:
        raise ValueError(f"The sheet has only {len(rows)} rows, so row {h} cannot be the header.")
    header = rows[h - 1]
    body = [r for r in rows[h:] if any(x not in (None, "") for x in r)]
    width = max([len(header)] + [len(r) for r in body]) if body else len(header)
    names, seen = [], {}
    for i in range(width):
        n = str(header[i]).strip() if i < len(header) and header[i] not in (None, "") else f"Column {i + 1}"
        if n in seen:                       # keep duplicate names unique
            seen[n] += 1
            n = f"{n} ({seen[n]})"
        else:
            seen[n] = 1
        names.append(n)
    body = [list(r) + [None] * (width - len(r)) for r in body]
    return names, body


# ---------------------------------------------------------------- preparing the data
def prepare(names, body, mapping, filters, units, consts):
    """mapping: {'voltage','resistance','pressure','concentration','temperature'(optional)} -> column name.
    filters: [{'column','op','value'}]. Returns arrays in SI units plus a summary of what was dropped."""
    idx = {n: i for i, n in enumerate(names)}
    need = ["voltage", "resistance", "pressure", "concentration"]
    for k in need:
        if mapping.get(k) not in idx:
            raise ValueError(f"Choose a column for {k}.")
    col = lambda name: np.array([to_float(r[idx[name]]) for r in body], float)

    n_total = len(body)
    keep = np.ones(n_total, bool)
    steps = [{"step": "rows in file", "rows": n_total}]
    for f in filters or []:
        if f.get("column") not in idx:
            continue
        x = col(f["column"])
        val = float(f["value"])
        ok = np.isfinite(x) & OPS[f["op"]](np.nan_to_num(x, nan=-np.inf), val)
        keep &= ok
        steps.append({"step": f"{f['column']} {f['op']} {val:g}", "rows": int(keep.sum())})

    V = col(mapping["voltage"]) * UNITS["voltage"][units.get("voltage", "V")]
    Rr = col(mapping["resistance"]) * UNITS["resistance"][units.get("resistance", "ohm")]
    P = col(mapping["pressure"]) * UNITS["pressure"][units.get("pressure", "kPa")]
    C = col(mapping["concentration"]) * UNITS["concentration"][units.get("concentration", "%")]
    if mapping.get("temperature") in idx:
        T = col(mapping["temperature"])
        if units.get("temperature", "C") == "C":
            T = T + 273.15
    else:
        T = np.full(n_total, float(consts["T_fixed"]))

    with np.errstate(divide="ignore", invalid="ignore"):
        I = V / Rr
    valid = np.isfinite(V) & np.isfinite(Rr) & np.isfinite(P) & np.isfinite(C) & np.isfinite(T)
    keep &= valid
    steps.append({"step": "numbers present in all chosen columns", "rows": int(keep.sum())})
    keep &= (Rr != 0) & (I > 0) & (P > 0) & (T > 0) & (C > 0) & (C < 100)
    steps.append({"step": "usable (I > 0, P > 0, 0 < C < 100 %)", "rows": int(keep.sum())})
    if keep.sum() < 3:
        raise ValueError("Fewer than 3 usable rows after filtering. Check the column choices, units and filter.")
    rows = np.arange(n_total)[keep]
    return {"V": V[keep], "R": Rr[keep], "I": I[keep], "P": P[keep], "C": C[keep], "T": T[keep],
            "row": rows, "steps": steps}


# ---------------------------------------------------------------- physics
def knudsen_D(T, c):
    return (2.0 * c["a"] / 3.0) * np.sqrt(8.0 * R_CONST * T / (math.pi * c["M"]))


def bulk_D(T, P, c):
    return c["D0"] * (T / 273.0) ** c["alpha"] * (c["P0"] / P)


def basis(I, P, T, c):
    """u = A*p + B*q  with  p = K/Dk, q = K/Db, K = I R T L / (4 F S P)."""
    K = I * R_CONST * T * c["L"] / (4.0 * F_CONST * c["S"] * P)
    return K / knudsen_D(T, c), K / bulk_D(T, P, c)


def conc(I, P, T, A, B, c):
    p, q = basis(I, P, T, c)
    return 100.0 * (1.0 - np.exp(-(A * p + B * q)))


# ---------------------------------------------------------------- fitting
def levenberg_marquardt(fun, x0, max_iter=200, tol=1e-12):
    """Minimise sum(fun(x)^2). Returns x, the loss after each accepted step, and x at each step."""
    x = np.array(x0, float)
    r = fun(x)
    cost = float(r @ r)
    lam, hist, xs = 1e-3, [cost], [x.tolist()]
    for _ in range(max_iter):
        J = np.empty((r.size, x.size))
        for j in range(x.size):
            h = 1e-6 * max(1.0, abs(x[j]))
            xp, xm = x.copy(), x.copy()
            xp[j] += h
            xm[j] -= h
            J[:, j] = (fun(xp) - fun(xm)) / (2 * h)
        g, H = J.T @ r, J.T @ J
        while lam < 1e14:
            step = np.linalg.solve(H + lam * np.diag(np.diag(H) + 1e-15), -g)
            r_new = fun(x + step)
            c_new = float(r_new @ r_new)
            if np.isfinite(c_new) and c_new < cost:
                break
            lam *= 4.0
        else:
            break
        done = (cost - c_new) / max(cost, 1e-300) < tol
        x, r, cost, lam = x + step, r_new, c_new, max(lam / 3.0, 1e-15)
        hist.append(cost)
        xs.append(x.tolist())
        if done:
            break
    return x, hist, xs


CONDITIONS = [
    ("A_only", "1. Optimize A (B = 1)"),
    ("B_only", "2. Optimize B (A = 1)"),
    ("AB", "3. Optimize A and B"),
    ("K", "4. A = B = 1, optimize K"),
]


def fit_condition(key, I, P, T, C, c):
    """Fit one condition. Start from the closed-form linear least-squares solution of
    -ln(1 - C/100) = A p + B q, then refine with Levenberg-Marquardt on the C error (log space keeps
    every factor positive)."""
    p, q = basis(I, P, T, c)
    X = -np.log(1.0 - C / 100.0)
    pos = lambda v: max(float(v), 1e-9)
    if key == "A_only":
        x0 = [math.log(pos(p @ (X - q) / (p @ p)))]
        AB = lambda t: (math.exp(t[0]), 1.0)
    elif key == "B_only":
        x0 = [math.log(pos(q @ (X - p) / (q @ q)))]
        AB = lambda t: (1.0, math.exp(t[0]))
    elif key == "AB":
        sol = np.linalg.lstsq(np.column_stack([p, q]), X, rcond=None)[0]
        x0 = [math.log(pos(sol[0])), math.log(pos(sol[1]))]
        AB = lambda t: (math.exp(t[0]), math.exp(t[1]))
    else:   # K
        s = p + q
        x0 = [math.log(pos(s @ X / (s @ s)))]
        AB = lambda t: (math.exp(t[0]), math.exp(t[0]))
    best = None
    for name, start in (("straight-line least squares", x0), ("theory A = B = 1", [0.0] * len(x0))):
        t, hist, xs = levenberg_marquardt(lambda t: conc(I, P, T, *AB(t), c) - C, start)
        if best is None or hist[-1] < best[1][-1]:
            best = (t, hist, xs, name)
    A, B = AB(best[0])
    sA, sB = AB(x0)
    steps = [{"it": i, "A": AB(x)[0], "B": AB(x)[1], "SSE": h, "RMSE": math.sqrt(h / len(C))}
             for i, (x, h) in enumerate(zip(best[2], best[1]))]
    return A, B, best[1], {"linear_A": sA, "linear_B": sB, "start_used": best[3], "steps": steps}


def metrics(pred, C):
    e = pred - C
    ss = float(np.sum((C - C.mean()) ** 2))
    within = lambda t: float(np.mean(np.abs(e) <= t) * 100)
    return {"RMSE": float(np.sqrt(np.mean(e ** 2))), "MAE": float(np.mean(np.abs(e))),
            "MaxAE": float(np.max(np.abs(e))), "Bias": float(np.mean(e)),
            "R2": float(1 - np.sum(e ** 2) / ss) if ss > 0 else None, "n": int(len(e)),
            "within1": within(1), "within2": within(2), "within5": within(5)}


def per_level(pred, C):
    lv = np.unique(np.round(C, 6))
    if len(lv) > 30:
        return None
    out = []
    for v in lv:
        k = np.isclose(C, v)
        e = pred[k] - C[k]
        out.append({"C": float(v), "n": int(k.sum()), "mean_pred": float(pred[k].mean()),
                    "min_pred": float(pred[k].min()), "max_pred": float(pred[k].max()),
                    "MAE": float(np.mean(np.abs(e))), "RMSE": float(np.sqrt(np.mean(e ** 2))), "Bias": float(np.mean(e))})
    return out


def fit_all(d, c):
    I, P, T, C = d["I"], d["P"], d["T"], d["C"]
    models = [{"key": "theory", "label": "Theory (A = B = 1)", "A": 1.0, "B": 1.0, "iterations": 0, "history": []}]
    for key, label in CONDITIONS:
        A, B, hist, info = fit_condition(key, I, P, T, C, c)
        models.append({"key": key, "label": label, "A": A, "B": B, "iterations": len(hist) - 1, "history": hist,
                       "fit": info})
    four = models[1:5]
    A_avg = float(np.mean([mm["A"] for mm in four]))
    B_avg = float(np.mean([mm["B"] for mm in four]))
    models.append({"key": "avg", "label": "Average of 1–4 (A_avg, B_avg)", "A": A_avg, "B": B_avg,
                   "iterations": 0, "history": []})
    for mm in models:
        pred = conc(I, P, T, mm["A"], mm["B"], c)
        mm["pred"] = pred.tolist()
        mm["metrics"] = metrics(pred, C)
        mm["per_level"] = per_level(pred, C)
    return models


def run(names, body, mapping, filters, units, consts):
    c = {**DEFAULT_CONSTANTS, **{k: float(v) for k, v in (consts or {}).items() if k in DEFAULT_CONSTANTS}}
    d = prepare(names, body, mapping, filters, units, c)
    models = fit_all(d, c)
    return {
        "constants": c, "mapping": mapping, "filters": filters, "units": units,
        "steps": d["steps"],
        "data": {"row": (d["row"] + 1).tolist(), "V": d["V"].tolist(), "R": d["R"].tolist(),
                 "I_uA": (d["I"] * 1e6).tolist(), "P_kPa": (d["P"] / 1e3).tolist(),
                 "T_K": d["T"].tolist(), "C": d["C"].tolist()},
        "models": models,
        "ranges": {"P_kPa": [float(d["P"].min() / 1e3), float(d["P"].max() / 1e3)],
                   "C": [float(d["C"].min()), float(d["C"].max())],
                   "I_uA": [float(d["I"].min() * 1e6), float(d["I"].max() * 1e6)],
                   "T_K": [float(d["T"].min()), float(d["T"].max())]},
        "uses_T_column": mapping.get("temperature") in names,
    }


def predict(V, R, P, T, A, B, units, c):
    """One reading in the user's units -> concentration (%)."""
    I = V * UNITS["voltage"][units.get("voltage", "V")] / (R * UNITS["resistance"][units.get("resistance", "ohm")])
    Pp = P * UNITS["pressure"][units.get("pressure", "kPa")]
    Tk = (T + 273.15 if units.get("temperature", "C") == "C" else T) if T is not None else c["T_fixed"]
    return {"C": float(conc(I, Pp, Tk, A, B, c)), "I_uA": I * 1e6, "P_kPa": Pp / 1e3, "T_K": Tk}


def evaluate(result, A, B):
    """Concentration for every fitted row of the uploaded file with a user-chosen A and B (nothing optimized)."""
    d, c = result["data"], result["constants"]
    I = np.array(d["I_uA"]) * 1e-6
    P = np.array(d["P_kPa"]) * 1e3
    T = np.array(d["T_K"])
    C = np.array(d["C"])
    pred = conc(I, P, T, A, B, c)
    return {"key": "custom", "label": f"Custom (A = {A:g}, B = {B:g})", "A": A, "B": B,
            "iterations": 0, "history": [], "pred": pred.tolist(),
            "metrics": metrics(pred, C), "per_level": per_level(pred, C)}
