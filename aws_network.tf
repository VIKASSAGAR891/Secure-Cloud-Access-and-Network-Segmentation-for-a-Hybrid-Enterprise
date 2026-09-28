# --------------------------------------------------------------------
# AWS side of the hybrid architecture - VPC + Zones 1-4
#
# Zone 1: Office       -> 10.10.1.0/24
# Zone 2: Management   -> 10.10.2.0/24
# Zone 3: Application  -> 10.10.3.0/24
# Zone 4: Third-Party  -> 10.10.4.0/24
#
# Zone 5: Cloud lives on the Azure side and is unchanged.
#
# CIDR plan matches Section 3 of the Zero Trust Architecture &
# Segmentation Policy document.
# --------------------------------------------------------------------

resource "aws_vpc" "thinkix_main" {
  cidr_block           = "10.10.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name    = "thinkix-hybrid-vpc"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

# --------------------------------------------------------------------
# Terraform state continuity
# --------------------------------------------------------------------
#
# Existing AWS subnet:
#   aws_subnet.public_a
#
# Becomes:
#   aws_subnet.office
#
# CIDR remains 10.10.1.0/24, so the existing subnet is preserved.
#
moved {
  from = aws_subnet.public_a
  to   = aws_subnet.office
}

# Existing AWS subnet:
#   aws_subnet.private_app
#
# Becomes:
#   aws_subnet.application
#
# Its CIDR changes from:
#   10.10.2.0/24
#
# to:
#   10.10.3.0/24
#
# AWS requires the subnet to be replaced when its CIDR changes.
#
moved {
  from = aws_subnet.private_app
  to   = aws_subnet.application
}


# ====================================================================
# ZONE 1 - OFFICE
# CIDR: 10.10.1.0/24
# ====================================================================

resource "aws_subnet" "office" {
  vpc_id                  = aws_vpc.thinkix_main.id
  cidr_block              = "10.10.1.0/24"
  availability_zone       = "ap-southeast-2a"
  map_public_ip_on_launch = false

  tags = {
    Name    = "thinkix-office-zone"
    Zone    = "1-Office"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_security_group" "office_zone_sg" {
  name        = "thinkix-office-zone-sg"
  description = "Default-deny security group for Office Zone - VLAN isolation, least-privilege endpoint access"
  vpc_id      = aws_vpc.thinkix_main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "thinkix-office-zone-sg"
    Zone    = "1-Office"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}


# ====================================================================
# ZONE 2 - MANAGEMENT
# CIDR: 10.10.2.0/24
# ====================================================================

resource "aws_subnet" "management" {
  vpc_id                  = aws_vpc.thinkix_main.id
  cidr_block              = "10.10.2.0/24"
  availability_zone       = "ap-southeast-2a"
  map_public_ip_on_launch = false

  tags = {
    Name    = "thinkix-management-zone"
    Zone    = "2-Management"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_security_group" "management_zone_sg" {
  name        = "thinkix-management-zone-sg"
  description = "Default-deny security group for Management Zone - RBAC + MFA, privileged admin access only"
  vpc_id      = aws_vpc.thinkix_main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "thinkix-management-zone-sg"
    Zone    = "2-Management"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}


# ====================================================================
# ZONE 3 - APPLICATION
# CIDR: 10.10.3.0/24
# ====================================================================

resource "aws_subnet" "application" {
  vpc_id                  = aws_vpc.thinkix_main.id
  cidr_block              = "10.10.3.0/24"
  availability_zone       = "ap-southeast-2a"
  map_public_ip_on_launch = true

  tags = {
    Name    = "thinkix-application-zone"
    Zone    = "3-Application"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_security_group" "app_zone_sg" {
  name        = "thinkix-app-zone-sg"
  description = "Default-deny security group for Application Zone - SDN micro-firewalls, app-layer only"
  vpc_id      = aws_vpc.thinkix_main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "thinkix-app-zone-sg"
    Zone    = "3-Application"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}


# ====================================================================
# ZONE 4 - THIRD-PARTY
# CIDR: 10.10.4.0/24
# ====================================================================

resource "aws_subnet" "third_party" {
  vpc_id                  = aws_vpc.thinkix_main.id
  cidr_block              = "10.10.4.0/24"
  availability_zone       = "ap-southeast-2a"
  map_public_ip_on_launch = false

  tags = {
    Name    = "thinkix-third-party-zone"
    Zone    = "4-ThirdParty"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_security_group" "third_party_zone_sg" {
  name        = "thinkix-third-party-zone-sg"
  description = "Default-deny security group for Third-Party Zone - SDP-only, single named application access"
  vpc_id      = aws_vpc.thinkix_main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "thinkix-third-party-zone-sg"
    Zone    = "4-ThirdParty"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}