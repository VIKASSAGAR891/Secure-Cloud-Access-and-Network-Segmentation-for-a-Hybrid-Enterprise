# --------------------------------------------------------------------
# Cloudflare Tunnel token - injected into the EC2 instance's user_data
# so the tunnel auto-installs on every launch/rebuild, without needing
# a manual Session Manager step each time. Marked sensitive so it
# never prints in plan/apply output. Supply the actual value via
# terraform.tfvars (gitignored) or TF_VAR_cloudflare_tunnel_token env var -
# never commit the real token to the repo.
# --------------------------------------------------------------------

variable "cloudflare_tunnel_token" {
  description = "Cloudflare Tunnel token for thinkix-app-tunnel (from Zero Trust dashboard > Tunnels > Configure)"
  type        = string
  sensitive   = true
}