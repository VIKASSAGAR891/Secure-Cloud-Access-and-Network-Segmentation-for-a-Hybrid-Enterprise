# --------------------------------------------------------------------
# EC2 instance in the Application Zone - hosts the test app and runs
# cloudflared directly, removing dependency on any team member's
# laptop. No inbound ports are opened; access for configuration is
# via AWS Systems Manager Session Manager (identity-based, no SSH keys,
# no open port 22) - consistent with the project's Zero Trust principles.
# --------------------------------------------------------------------

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

# IAM role allowing Systems Manager to manage this instance -
# this is what replaces SSH entirely.
resource "aws_iam_role" "ssm_role" {
  name = "thinkix-app-ec2-ssm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = {
    Project = "ThinkiX-ZeroTrust"
  }
}


resource "aws_iam_role_policy_attachment" "ssm_attach" {
  role       = aws_iam_role.ssm_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ssm_profile" {
  name = "thinkix-app-ec2-ssm-profile"
  role = aws_iam_role.ssm_role.name
}

resource "aws_instance" "app_server" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t3.micro" # AWS Free Tier eligible
  subnet_id              = aws_subnet.application.id
  vpc_security_group_ids = [aws_security_group.app_zone_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_profile.name

  # No key_name set deliberately - no SSH key pair needed at all,
  # since access is via SSM Session Manager only.

   user_data = <<-EOF
    #!/bin/bash
    dnf update -y
    dnf install -y nginx
    systemctl enable nginx
    systemctl start nginx

    cat <<'HTML' > /usr/share/nginx/html/index.html
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>ThinkiX Zero Trust - Application Zone</title>
      <style>
        body { font-family: Georgia, serif; max-width: 700px; margin: 60px auto; padding: 0 20px; color: #1a1a1a; }
        h1 { font-size: 1.8em; }
        .zone-tag { display: inline-block; background: #f0f0f0; padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 0.85em; }
        .footer { margin-top: 40px; font-size: 0.85em; color: #666; }
      </style>
    </head>
    <body>
      <h1>ThinkiX Zero Trust Hybrid Architecture</h1>
      <p><span class="zone-tag">Zone 3 &middot; Application</span></p>
      <p>This workload runs inside the Application Zone (10.10.3.0/24) of ThinkiX's 5-zone
      Zero Trust hybrid architecture, reached exclusively via Cloudflare Tunnel &mdash; no inbound
      ports are open on this instance.</p>
      <div class="footer">MN690/MN692 &middot; ThinkiX &middot; Melbourne Institute of Technology</div>
    </body>
    </html>
    HTML

    systemctl restart nginx

    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-x86_64.rpm -o /tmp/cloudflared.rpm
    dnf install -y /tmp/cloudflared.rpm

    cloudflared service install ${var.cloudflare_tunnel_token}
    systemctl enable --now cloudflared
  EOF

tags = {
Name = "thinkix-app-server"
Zone = "3-Application"
}


  lifecycle {
    ignore_changes = [ami]
  }
}