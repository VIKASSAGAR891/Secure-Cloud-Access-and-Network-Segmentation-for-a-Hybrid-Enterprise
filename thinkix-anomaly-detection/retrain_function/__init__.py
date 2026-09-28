"""
Runs weekly (Sundays 02:00 UTC). Pulls a fresh rolling 14-day window of
AWSVPCFlow, retrains both models, and uploads the new version to Blob
Storage as "latest" -- the scoring function will pick it up on its next
cold start (Consumption plan instances recycle frequently enough that
this typically happens within an hour; see notes in README about forcing
a faster rollout if needed).

The previous "latest" is archived (not deleted) by model_registry.upload_new_version,
so a bad retrain can be rolled back manually by copying an archive/ version
back to latest/ in Blob Storage.
"""

import logging
import os
import tempfile
from datetime import datetime, timedelta

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

from .feature_engineering import build_features
from .model_registry import upload_new_version
from .train_model import train

WORKSPACE_ID = os.environ["WORKSPACE_ID"]
BASELINE_DAYS = int(os.environ.get("RETRAIN_WINDOW_DAYS", "14"))

QUERY_TEMPLATE = """
AWSVPCFlow
| where TimeGenerated between (startofday(ago({days}d)) .. now())
| where SrcAddr startswith "10.10." and DstAddr startswith "10.10."
| project TimeGenerated, SrcAddr, DstAddr, SrcPort, DstPort, Protocol, Packets, Bytes
"""


def main(timer: func.TimerRequest) -> None:
    logging.info(f"Weekly retrain starting, pulling last {BASELINE_DAYS} days")

    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)
    response = client.query_workspace(
        workspace_id=WORKSPACE_ID,
        query=QUERY_TEMPLATE.format(days=BASELINE_DAYS),
        timespan=timedelta(days=BASELINE_DAYS),
        server_timeout=300,
    )

    if response.status != LogsQueryStatus.SUCCESS:
        logging.error(f"Retrain query failed: {response}")
        return

    import pandas as pd

    table = response.tables[0]
    raw = pd.DataFrame(table.rows, columns=table.columns)
    raw["TimeGenerated"] = pd.to_datetime(raw["TimeGenerated"])

    if raw.empty:
        logging.warning("No data returned for retrain window, skipping this cycle")
        return

    features, _ = build_features(raw)

    with tempfile.TemporaryDirectory() as tmp_dir:
        features_path = f"{tmp_dir}/features.parquet"
        features.to_parquet(features_path, index=False)

        train(features_path, model_dir=tmp_dir)

        version_tag = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
        upload_new_version(tmp_dir, version_tag)

    logging.info(f"Retrain complete, uploaded new model version {version_tag}")
