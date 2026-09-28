# --------------------------------------------------------------------
# Internet Gateway - gives the Application zone outbound internet
# access (needed for SSM Agent registration, dnf updates, and the
# cloudflared download). Inbound remains fully blocked by
# aws_security_group.app_zone_sg - no ports are opened.
# --------------------------------------------------------------------

resource "aws_internet_gateway" "thinkix_igw" {
  vpc_id = aws_vpc.thinkix_main.id

  tags = {
    Name    = "thinkix-igw"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_route_table" "application_rt" {
  vpc_id = aws_vpc.thinkix_main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.thinkix_igw.id
  }

  tags = {
    Name    = "thinkix-application-rt"
    Zone    = "3-Application"
    Project = "ThinkiX-ZeroTrust"
    Managed = "Terraform"
  }
}

resource "aws_route_table_association" "application_rt_assoc" {
  subnet_id      = aws_subnet.application.id
  route_table_id = aws_route_table.application_rt.id
}