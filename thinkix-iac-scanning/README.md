# Infrastructure-as-Code Security Scanning

Implements the CI enforcement half of Section 3.1.5 of the report: Checkov
and Terrascan run in parallel on every Terraform pull request, and block
the merge on CRITICAL/HIGH severity findings.

## Setup (10 minutes)

1. Copy `.github/workflows/iac-scan.yml` into the root of your Terraform
   repo (`thinkix-terraform`), preserving the `.github/workflows/` path.

2. Commit and push it to a branch, then open a PR — GitHub will
   automatically detect the workflow and start running it on any PR that
   touches a `.tf` file.

3. **Turn on branch protection** so this actually blocks bad merges,
   rather than just reporting a status that people can ignore:
   - GitHub repo → **Settings → Branches → Add branch protection rule**
   - Branch name pattern: `main`
   - Enable **"Require status checks to pass before merging"**
   - Search for and select both `Checkov scan` and `Terrascan scan`
   - Save

   Without this step, the workflow runs and reports results, but nothing
   stops someone from merging anyway — the branch protection rule is what
   makes it a real gate, not just a report.

## Demoing this on Monday

The most convincing thing you can show is the gate **actually catching
something and blocking it** — not just a green checkmark, since a green
checkmark alone doesn't prove the gate works, it could just mean nothing
ran.

**Quick way to prove it blocks a real issue:** create a throwaway branch,
add an obviously permissive Security Group rule to any `.tf` file, e.g.:

```hcl
resource "aws_security_group_rule" "demo_bad_rule" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]   # <- SSH open to the entire internet
  security_group_id = aws_security_group.app_zone.id
}
```

Open a PR with just that change. Checkov will flag this (it's a textbook
"SSH open to 0.0.0.0/0" finding, one of the most common IaC misconfigs it
checks for) and the PR's required status check will show **red/failing**,
which — with branch protection enabled — blocks the merge button.

Screenshot that failing check and the specific finding in the PR. That's
concrete proof the gate works, not just proof the workflow file exists.
Then close the PR without merging (don't actually add this rule to real
infrastructure).

## What this does NOT do yet (be upfront about this if asked)

- It scans and blocks on merge; it does not automatically **fix** or
  **push segmentation policy** the way the report's SDN controller
  description implies ("implements the relevant segmentation policy
  before the cloud resource is made reachable") — that's a larger,
  separate piece (something like an OPA/Conftest policy engine wired into
  the apply step, not just the PR gate) and is a reasonable thing to scope
  into MN692 rather than claim as done now.
- `iac_version: v14` in the Terrascan step should be checked against
  whatever Terraform version the repo actually pins — update if it drifts.
- Some Checkov checks may not fit this specific VPC's design (e.g., a
  check assuming NAT Gateway when this environment deliberately uses an
  Internet Gateway for cost reasons) — false positives can be suppressed
  via `skip_check` in the workflow file, but do that deliberately and
  document why, not just to make the gate pass.
