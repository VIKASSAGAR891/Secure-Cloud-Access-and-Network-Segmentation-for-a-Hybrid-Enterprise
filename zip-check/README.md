# ThinkiX East-West Anomaly Detection (Phase 4)

Autoencoder + Isolation Forest ensemble for detecting anomalous East-West
(intra-VPC) traffic, trained on a rolling baseline, with auto-block above
a 0.85 confidence threshold. Builds on top of the working CloudTrail +
VPC Flow Logs → Sentinel pipeline from Phases 2-3.

## Architecture

```
AWSVPCFlow (Sentinel)
        │
        ├── data_export/  ──────────────► one-time: pull 2-week baseline
        │                                 for initial training
        │
        ├── scoring_function/  ─────────► runs every 5 min, scores recent
        │                                 traffic, calls Playbook if >= 0.85
        │
        └── retrain_function/  ─────────► runs weekly, retrains on fresh
                                          14-day window, publishes new model
                                          version to Blob Storage

Model artifacts live in Blob Storage (models/latest/, models/archive/<ts>/),
NOT on the Function App's local disk -- see scoring_function/model_registry.py
for why.
```

## Status: NOT YET RUNNABLE END TO END

This is scaffolding, built ahead of the 2-week baseline period so there's
no lost time once real data exists. Still needed before this works:

1. **Wait for baseline data.** VPC Flow Logs started flowing into Sentinel
   on 2026-09-02. Don't run `train_model.py` for real until ~2026-09-16 --
   training on less than the full 2-week window will bake a skewed
   "normal" into the model.

2. **Create the Blob Storage account** for model artifacts:
   ```powershell
   aws configure  # not needed -- this one's Azure
   az storage account create --name thinkixmodels --resource-group thinkix-hybrid-rg --sku Standard_LRS
   az storage container create --account-name thinkixmodels --name anomaly-models
   ```
   (adjust names/RG to match your actual Azure resource group)

3. **Create the Sentinel Playbook (Logic App)** that performs the actual
   block action. **Important architecture note**: a Logic App cannot call
   AWS APIs directly (no native AWS connector, and hand-rolling AWS SigV4
   auth in a Logic App HTTP action is painful and fragile). Instead, the
   Playbook should be a thin, Sentinel-native wrapper that calls
   `block_executor` (see below) to do the real work -- this keeps the
   Sentinel-side audit trail and incident correlation while letting a
   normal Python function handle AWS auth via boto3.

   `block_executor/` is a separate Azure Function (HTTP-triggered) that
   performs the actual block: it adds a **Network ACL deny rule** for the
   flagged source IP, scoped to whichever subnet that IP lives in.
   **This uses NACLs, not Security Groups** -- AWS Security Groups are
   allow-only and have no deny rule type, so a NACL is the correct
   primitive for "block this one IP without touching anyone else's
   access." Every block is recorded in Blob Storage (`blocks/` prefix in
   the model container) with a timestamp and status, and there's a
   matching `unblock` action (`?action=unblock`) so a false positive can
   be reversed with one call rather than requiring manual AWS console
   surgery.

   `block_executor` needs its own AWS credentials, since it can't use
   `OIDC_ThinkiXSentinelRole` (that role's trust policy is scoped to
   Sentinel's own app registration/audience, not this Function App).
   Create a dedicated, minimally-scoped IAM user:
   ```powershell
   aws iam create-user --user-name thinkix-block-executor
   aws iam put-user-policy --user-name thinkix-block-executor --policy-name NaclBlockExecutorAccess --policy-document file://block_executor/iam-policy.json
   aws iam create-access-key --user-name thinkix-block-executor
   ```
   Save the returned `AccessKeyId` and `SecretAccessKey` -- you'll set
   these as Function App secrets in step 4.

   Once `block_executor` is deployed and tested (see step 5), build the
   actual Sentinel Playbook as a Logic App with an HTTP trigger, and have
   its one meaningful action be an HTTP POST to `block_executor`'s URL.
   `PLAYBOOK_WEBHOOK_URL` (used by `scoring_function`) should point at
   this Logic App's trigger URL, not directly at `block_executor` --
   keeping the Logic App in the loop is what gives you the Sentinel
   incident timeline/audit trail described in the report.

4. **Deploy the Function Apps.** `scoring_function/`, `retrain_function/`,
   and `block_executor/` are three separate functions -- deploy them into
   one Function App (simplest) or split across apps. Set these
   Application Settings:
   - `WORKSPACE_ID` — the Sentinel/Log Analytics workspace ID
     (`aec13dda-4411-4f2c-a3d9-bc14d20badcf`, confirm this is still current)
   - `PLAYBOOK_WEBHOOK_URL` — the Sentinel Playbook's HTTP trigger URL (step 3)
   - `MODEL_STORAGE_ACCOUNT_URL` — e.g. `https://thinkixmodels.blob.core.windows.net`
   - `MODEL_CONTAINER_NAME` — `anomaly-models`
   - `CONFIDENCE_THRESHOLD` — defaults to 0.85, override here without redeploying
   - `DRY_RUN` — defaults to `"true"`. While true, flagged hosts are only
     logged, never actually blocked. **Leave this as `true` for the first
     1-2 weeks after deploying**, review what it would have flagged in the
     Function's logs/App Insights, then set to `"false"` once you trust it.
   - `RETRAIN_WINDOW_DAYS` — defaults to 14
   - `TARGET_VPC_ID` — `vpc-06bc9c2aa8d32526b` (needed by `block_executor` only)
   - `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` —
     the `thinkix-block-executor` IAM user's credentials from step 3
     (needed by `block_executor` only -- consider moving these to Azure
     Key Vault references once things are stable, rather than leaving
     raw keys as plain Application Settings)
   - The Function App's **Managed Identity** needs `Reader` +
     `Log Analytics Reader` on the Log Analytics workspace and
     `Storage Blob Data Contributor` on the model container (all already
     granted if you followed the setup so far).

5. **Run the first training pass manually** once baseline data exists:
   ```powershell
   cd data_export
   pip install -r ../scoring_function/requirements.txt azure-monitor-query azure-identity
   python export_logs.py --days 14 --out ../training/baseline_flows.parquet

   cd ../training
   python feature_engineering.py baseline_flows.parquet
   python train_model.py --features baseline_features.parquet

   # then manually upload models/ to Blob Storage as models/latest/
   # (or write a small one-off script using model_registry.upload_new_version)
   ```

## Open decisions to make before Phase 4 is actually complete

- **What does "auto-block" concretely do?** NSG rule, WAF rule, instance
  isolation, something else? Blocks the Playbook design in step 3.
- **Contamination rate (2% in `train_model.py`)** is a starting guess for
  the Isolation Forest -- revisit once you've seen real baseline data and
  have a sense of what fraction of traffic is legitimately unusual
  (backups, batch jobs, etc.) vs. actually suspicious.
- **Score combination weights (50/50 in `combine_scores.py`)** are
  arbitrary until you have real flagged incidents to check against.
- **Alerting/visibility before auto-block goes live.** Already handled by
  the `DRY_RUN` flag in `scoring_function/__init__.py` — it defaults to
  `true`, so flagged hosts are logged but nothing gets blocked until you
  explicitly flip it off in the Function App's settings.
