"""Zirconia O2 sensor: upload an Excel/CSV, choose columns and filters, fit A and B four ways.

Run:  python app.py      (or from Jupyter: run.ipynb), then open http://127.0.0.1:5050
"""
import os
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from flask import Flask, jsonify, render_template, request

import upload_model as um

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5050"))

app = Flask(__name__, static_folder="static", template_folder="templates")
UPLOAD = {}     # the file currently loaded (one user, local app)


@app.get("/")
def page():
    return render_template("fit.html")


@app.get("/condition/<key>")
def condition_page(key):
    return render_template("detail.html")


@app.get("/api/state")
def api_state():
    """What is loaded right now, so a page can be reloaded (or reached with Back) without losing results."""
    if "names" not in UPLOAD:
        return jsonify({"table": None, "result": None})
    return jsonify({"table": _table_info(), "result": UPLOAD.get("result")})


def _table_info():
    names, body = um.table(UPLOAD["rows"], UPLOAD["header_row"])
    UPLOAD["names"], UPLOAD["body"] = names, body
    numeric = [int(sum(bool(np.isfinite(um.to_float(r[i]))) for r in body)) for i in range(len(names))]
    return {"filename": UPLOAD["filename"], "sheets": UPLOAD["sheets"], "sheet": UPLOAD["sheet"],
            "header_row": UPLOAD["header_row"], "columns": names, "n_rows": len(body), "numeric": numeric,
            "preview": [[None if v is None else (v if isinstance(v, str) else float(v)) for v in r] for r in body[:8]],
            "ops": list(um.OPS), "constants": um.DEFAULT_CONSTANTS}


@app.post("/api/upload")
def api_upload():
    """New file (multipart 'file'), or re-read the current one with another sheet / header row (JSON)."""
    try:
        if "file" in request.files:
            f = request.files["file"]
            UPLOAD.clear()
            UPLOAD.update(filename=f.filename, data=f.read(), header_row=1)
            sheet = None
        else:
            if not UPLOAD:
                raise ValueError("Upload a file first.")
            body = request.get_json(silent=True) or {}
            sheet = body.get("sheet") or UPLOAD.get("sheet")
            UPLOAD["header_row"] = max(1, int(body.get("header_row", UPLOAD["header_row"])))
        loaded = um.load_file(UPLOAD["filename"], UPLOAD["data"], sheet)
        UPLOAD.update(rows=loaded["rows"], sheets=loaded["sheets"], sheet=loaded["sheet"])
        return jsonify(_table_info())
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as exc:
        return jsonify({"error": str(exc) or "Could not read this file."}), 400


@app.post("/api/fit")
def api_fit():
    body = request.get_json(silent=True) or {}
    try:
        if "names" not in UPLOAD:
            raise ValueError("Upload a file first.")
        res = um.run(UPLOAD["names"], UPLOAD["body"], body.get("mapping", {}), body.get("filters", []),
                     body.get("units", {}), body.get("constants", {}))
    except (ValueError, KeyError, np.linalg.LinAlgError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400
    res["filename"] = UPLOAD["filename"]
    UPLOAD["result"] = res
    return jsonify(res)


@app.post("/api/predict")
def api_predict():
    body = request.get_json(silent=True) or {}
    res = UPLOAD.get("result")
    if not res:
        return jsonify({"error": "Run the optimization first."}), 400
    try:
        V, R, P = float(body["V"]), float(body["R"]), float(body["P"])
        T = float(body["T"]) if res["uses_T_column"] else None
        if R == 0 or P <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Enter voltage, resistance (not 0) and pressure (> 0)" +
                                 (" and temperature" if res["uses_T_column"] else "")}), 400
    out = [{"key": m["key"], "label": m["label"],
            "C": um.predict(V, R, P, T, m["A"], m["B"], res["units"], res["constants"])["C"]} for m in res["models"]]
    r0 = um.predict(V, R, P, T, 1.0, 1.0, res["units"], res["constants"])
    return jsonify({"models": out, "I_uA": r0["I_uA"], "P_kPa": r0["P_kPa"], "T_K": r0["T_K"]})


if __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
