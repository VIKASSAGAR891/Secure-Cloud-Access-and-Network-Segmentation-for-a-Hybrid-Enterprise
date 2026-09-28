# --------------------------------------------------------------------
# Microsoft Sentinel - centralised log
# analytics workspace with Sentinel enabled on top. Log sources
# (AWS CloudTrail via S3/SQS connector, Azure Monitor/NSG flow logs)
# are wired in as separate steps once the workspace exists.
# --------------------------------------------------------------------

resource "azurerm_log_analytics_workspace" "thinkix_siem" {
  name                = "thinkix-siem-workspace"
  location            = azurerm_resource_group.thinkix_rg.location
  resource_group_name = azurerm_resource_group.thinkix_rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 90 # keep >= 90 days for compliance/audit review per report
  daily_quota_gb = 1

  tags = {
    Project = "ThinkiX-ZeroTrust"
    Purpose = "Centralised-SIEM"
  }
}

# Onboards Microsoft Sentinel onto the workspace above.
resource "azurerm_sentinel_log_analytics_workspace_onboarding" "thinkix_sentinel" {
  workspace_id                 = azurerm_log_analytics_workspace.thinkix_siem.id
  customer_managed_key_enabled = false
}

output "sentinel_workspace_name" {
  value = azurerm_log_analytics_workspace.thinkix_siem.name
}

output "sentinel_workspace_id" {
  value = azurerm_log_analytics_workspace.thinkix_siem.workspace_id
}