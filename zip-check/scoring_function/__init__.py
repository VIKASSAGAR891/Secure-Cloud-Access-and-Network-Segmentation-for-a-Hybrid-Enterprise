"""
Timer-triggered Azure Function (runs every 5 minutes, matching the feature
window used in training).

Each run:
  1. Pulls the last ~10 minutes of AWSVPCFlow from Sentinel (overlapping
     window to avoid gaps at window boundaries)
  2. Builds the same feature vectors used in training
  3. Scores them with the autoencoder + isolation forest
  4. For any host/window scoring >= CONFIDENCE_THRESHOLD, calls the
     Sentinel Playbook (Logic App) webhook to trigger the auto-block action

Environment variables required (set in Function App > Configuration):
  WORKSPACE_ID           - Log Analytics workspace ID
  PLAYBOOK_WEBHOOK_URL   - Logic App HTTP trigger URL for the block playbook
  MODEL_DIR              - path models were deployed to (default "models")
  CONFIDENCE_THRESHOLD   - default 0.85, overridable for tuning without redeploy
"""

import json
import logging
import os
from datetime import timedelta

import joblib
import numpy as np
import pandas as pd
import requests
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from tensorflow import keras

import azure.functions as func

# these two modules are deployed alongside this function -- see requirements
# on keeping training/ and scoring_function/ feature logic in sync
from combine_scores import combine
from feature_engineering import build_features
from model_registry import download_latest

WORKSPACE_ID = os.environ["WORKSPACE_ID"]
PLAYBOOK_WEBHOOK_URL = os.environ["PLAYBOOK_WEBHOOK_URL"]
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
# Safety switch: while true, flagged hosts are logged (and visible via the
# function's own logs / App Insights) but the Playbook is NOT called.
# Flip to "false" only after you've reviewed a week or two of dry-run output
# and are comfortable with what it would have blocked.
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

RECENT_QUERY = """
AWSVPCFlow
| where TimeGenerated > ago(10m)
| where SrcAddr startswith "10.10." and DstAddr startswith "10.10."
| project TimeGenerated, SrcAddr, DstAddr, SrcPort, DstPort, Protocol, Packets, Bytes
"""


def _load_models():
    model_dir = download_latest()
    scaler = joblib.load(f"{model_dir}/scaler.joblib")
    iso = joblib.load(f"{model_dir}/isolation_forest.joblib")
    ae = keras.models.load_model(f"{model_dir}/autoencoder.keras")
    with open(f"{model_dir}/metadata.json") as f:
        metadata = json.load(f)
    return scaler, iso, ae, metadata


def _fetch_recent_flows() -> pd.DataFrame:
    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)
    response = client.query_workspace(
        workspace_id=WORKSPACE_ID,
        query=RECENT_QUERY,
        timespan=timedelta(minutes=10),
    )
    if response.status != LogsQueryStatus.SUCCESS:
        raise RuntimeError(f"Log query failed: {response}")

    table = response.tables[0]
    df = pd.DataFrame(table.rows, columns=table.columns)
    if not df.empty:
        df["TimeGenerated"] = pd.to_datetime(df["TimeGenerated"])
    return df


def _trigger_block(src_addr: str, confidence: float, window: str) -> None:
    payload = {
        "sourceHost": src_addr,
        "confidence": confidence,
        "window": window,
        "reason": "East-West traffic anomaly detection (autoencoder + isolation forest ensemble)",
    }
    resp = requests.post(PLAYBOOK_WEBHOOK_URL, json=payload, timeout=30)
    resp.raise_for_status()
    logging.warning(f"Triggered block playbook for {src_addr} (confidence={confidence:.3f})")


def main(timer: func.TimerRequest) -> None:
    logging.info("Anomaly scoring run starting")

    raw = _fetch_recent_flows()
    if raw.empty:
        logging.info("No flow records in the last window, nothing to score")
        return

    features, feature_cols = build_features(raw)
    if features.empty:
        logging.info("No feature rows built from this window")
        return

    scaler, iso, ae, metadata = _load_models()

    X = features[metadata["feature_cols"]].values.astype("float32")
    X_scaled = scaler.transform(X)

    reconstructions = ae.predict(X_scaled, verbose=0)
    reconstruction_errors = np.mean(np.square(X_scaled - reconstructions), axis=1)
    iso_scores = iso.decision_function(X_scaled)

    confidences = combine(reconstruction_errors, iso_scores, metadata["ae_error_p99"])
    features["confidence"] = confidences

    flagged = features[features["confidence"] >= CONFIDENCE_THRESHOLD]

    logging.info(f"Scored {len(features)} host/window samples, {len(flagged)} above threshold")

    for _, row in flagged.iterrows():
        if DRY_RUN:
            logging.warning(
                f"[DRY RUN] Would trigger block for {row['SrcAddr']} "
                f"(confidence={row['confidence']:.3f}, window={row['window']}) "
                f"-- set DRY_RUN=false in Application Settings to actually block"
            )
        else:
            _trigger_block(
                src_addr=row["SrcAddr"],
                confidence=float(row["confidence"]),
                window=str(row["window"]),
            )
