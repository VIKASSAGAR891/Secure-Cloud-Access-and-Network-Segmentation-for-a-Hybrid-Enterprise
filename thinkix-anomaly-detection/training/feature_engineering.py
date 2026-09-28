"""
Turns raw VPC flow log records into per-host, time-windowed feature vectors
suitable for the autoencoder and isolation forest.

Design notes:
- Raw flow records are per-connection; anomaly detection on East-West
  traffic works better on aggregated behavior per (source host, time
  window) than on individual flows, since a single flow is too sparse
  a signal and floods the models with noise.
- Window size defaults to 5 minutes, matching a reasonable middle ground
  between the 10-minute VPC Flow Log aggregation interval and wanting
  enough resolution to catch fast scanning/lateral-movement behavior.
- All features are engineered to be scale-invariant or log-transformed
  where appropriate, since raw byte/packet counts are heavily skewed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = "5min"


def load_raw(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    df["TimeGenerated"] = pd.to_datetime(df["TimeGenerated"])
    for col in ("SrcPort", "DstPort", "Protocol", "Packets", "Bytes"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["SrcAddr", "DstAddr", "SrcPort", "DstPort", "Protocol"])
    return df


def _well_known_port(port: int) -> bool:
    return port < 1024


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates raw flows into (SrcAddr, time window) feature rows.
    One row per source host per window == one "sample" for the models.
    """
    df = df.copy()
    df["window"] = df["TimeGenerated"].dt.floor(WINDOW)
    df["is_well_known_dst_port"] = df["DstPort"].apply(_well_known_port)

    grouped = df.groupby(["SrcAddr", "window"])

    feats = grouped.agg(
        flow_count=("DstAddr", "count"),
        unique_dst_hosts=("DstAddr", "nunique"),
        unique_dst_ports=("DstPort", "nunique"),
        total_bytes=("Bytes", "sum"),
        total_packets=("Packets", "sum"),
        mean_bytes_per_flow=("Bytes", "mean"),
        max_bytes_single_flow=("Bytes", "max"),
        pct_well_known_ports=("is_well_known_dst_port", "mean"),
        protocol_nunique=("Protocol", "nunique"),
    ).reset_index()

    # fan-out ratio: hosts contacted vs total flows -- high value suggests
    # scanning behavior (many distinct destinations, few flows each)
    feats["dst_fanout_ratio"] = feats["unique_dst_hosts"] / feats["flow_count"].clip(lower=1)

    # port-scan signal: many distinct destination ports contacted
    feats["port_fanout_ratio"] = feats["unique_dst_ports"] / feats["flow_count"].clip(lower=1)

    # log-transform heavy-tailed count/volume features
    for col in ("flow_count", "total_bytes", "total_packets", "mean_bytes_per_flow", "max_bytes_single_flow"):
        feats[f"log_{col}"] = np.log1p(feats[col])

    feature_cols = [
        "log_flow_count",
        "unique_dst_hosts",
        "unique_dst_ports",
        "log_total_bytes",
        "log_total_packets",
        "log_mean_bytes_per_flow",
        "log_max_bytes_single_flow",
        "pct_well_known_ports",
        "protocol_nunique",
        "dst_fanout_ratio",
        "port_fanout_ratio",
    ]

    return feats[["SrcAddr", "window"] + feature_cols], feature_cols


if __name__ == "__main__":
    import sys

    raw = load_raw(sys.argv[1] if len(sys.argv) > 1 else "baseline_flows.parquet")
    features, cols = build_features(raw)
    print(f"Built {len(features):,} feature rows across {features['SrcAddr'].nunique()} hosts")
    print(features[cols].describe())
    features.to_parquet("baseline_features.parquet", index=False)
    print("Wrote baseline_features.parquet")
