# --------------------------------------------------------------------
# Ingress rules implementing the segmentation matrix (Section 4 of the
# Zero Trust Architecture & Segmentation Policy document).
#
# Design principle: only the Application zone receives inbound traffic
# from other zones. Office, Management, and Third-Party never accept
# inbound from sibling zones — matching the "DENY — no direct path"
# entries in the traffic matrix.
#
# NOTE: These rules define what the network layer *permits*. They do
# NOT by themselves enforce identity/MFA verification — that's the
# job of the ZTNA broker and Zero Trust Policy Engine. Until those exist,
# these rules represent
# the outer boundary only.
# --------------------------------------------------------------------

# ===== Office -> Application (443/TLS, intended to route via ZTNA) =====
resource "aws_security_group_rule" "office_to_app" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app_zone_sg.id
  source_security_group_id = aws_security_group.office_zone_sg.id
  description               = "Office to Application - HTTPS only, intended to route via ZTNA broker"
}

# ===== Management -> Application (22 admin SSH + 443, intended via PAM JIT) =====
resource "aws_security_group_rule" "management_to_app_ssh" {
  type                     = "ingress"
  from_port                = 22
  to_port                  = 22
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app_zone_sg.id
  source_security_group_id = aws_security_group.management_zone_sg.id
  description               = "Management to Application - SSH, intended to route via PAM JIT session"
}

resource "aws_security_group_rule" "management_to_app_https" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app_zone_sg.id
  source_security_group_id = aws_security_group.management_zone_sg.id
  description               = "Management to Application - HTTPS, intended to route via PAM JIT session"
}

# ===== Third-Party -> Application (443/TLS, intended via SDP micro-tunnel) =====
resource "aws_security_group_rule" "thirdparty_to_app" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app_zone_sg.id
  source_security_group_id = aws_security_group.third_party_zone_sg.id
  description               = "Third-Party to Application - HTTPS only, intended to route via SDP micro-tunnel"
}

# ===== Cloud (Azure) -> Application (443/TLS) =====
# LIMITATION: No VPN tunnel or peering exists yet between AWS and Azure,
# so this is defined by CIDR only and is NOT yet a verified, connected
# path. This rule documents intent; it will not pass real traffic until
# cross-cloud connectivity is established (Week 6+ decision).
resource "aws_security_group_rule" "cloud_to_app" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  security_group_id = aws_security_group.app_zone_sg.id
  cidr_blocks       = ["10.20.0.0/16"]
  description        = "Cloud zone (Azure) to Application - HTTPS. Pending cross-cloud VPN/peering to be enforceable end-to-end."
}