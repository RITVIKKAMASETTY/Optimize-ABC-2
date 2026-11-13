"""Flask web app. Run:  python app.py   (or from Jupyter: run.ipynb)"""
import os
import numpy as np
from flask import Flask, jsonify, render_template, request

from model import DEFAULT_CONFIG, STATE, calibrate, clean_config, predict_point

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5050"))
# ---------- Flask app ----------
app = Flask(__name__, static_folder="static", template_folder="templates")


@app.get("/")
def index():
    return render_template("index.html")


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



if __name__ == "__main__":
    print(f"Open http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
