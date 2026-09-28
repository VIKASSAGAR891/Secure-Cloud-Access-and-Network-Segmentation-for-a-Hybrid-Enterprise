"""
Pulls East-West VPC flow log data out of the Sentinel workspace via the
Azure Monitor Query API and writes it to a local CSV/Parquet file for
model training.

Requires:
    pip install azure-monitor-query azure-identity pandas

Auth:
    Uses DefaultAzureCredential — run `az login` first, or set
    AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID env vars
    for a service principal (recommended for a scheduled/unattended run).

Usage:
    python export_logs.py --days 14 --out baseline_flows.parquet
"""

import argparse
import sys
from datetime import timedelta

import pandas as pd
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# ---- fill these in for your environment ----
WORKSPACE_ID = "aec13dda-4411-4f2c-a3d9-bc14d20badcf"  # the Sentinel workspace ID we saw in the connector page
# ---------------------------------------------

QUERY_TEMPLATE = """
AWSVPCFlow
| where TimeGenerated between (startofday(ago({days}d)) .. now())
| where SrcAddr startswith "10.10." and DstAddr startswith "10.10."
| project
    TimeGenerated,
    InterfaceId,
    SrcAddr,
    DstAddr,
    SrcPort,
    DstPort,
    Protocol,
    Packets,
    Bytes
| sort by TimeGenerated asc
"""


def export(days: int, out_path: str) -> None:
    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)

    query = QUERY_TEMPLATE.format(days=days)

    print(f"Querying last {days} days of AWSVPCFlow from workspace {WORKSPACE_ID} ...")
    response = client.query_workspace(
        workspace_id=WORKSPACE_ID,
        query=query,
        timespan=timedelta(days=days),
        server_timeout=300,  # large exports can take a while
    )

    if response.status != LogsQueryStatus.SUCCESS:
        print("Query failed or partially failed:", response, file=sys.stderr)
        sys.exit(1)

    table = response.tables[0]
    df = pd.DataFrame(table.rows, columns=table.columns)

    print(f"Retrieved {len(df):,} rows.")

    if out_path.endswith(".parquet"):
        df.to_parquet(out_path, index=False)
    else:
        df.to_csv(out_path, index=False)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="How many days back to pull")
    parser.add_argument("--out", type=str, default="baseline_flows.parquet")
    args = parser.parse_args()
    export(args.days, args.out)
