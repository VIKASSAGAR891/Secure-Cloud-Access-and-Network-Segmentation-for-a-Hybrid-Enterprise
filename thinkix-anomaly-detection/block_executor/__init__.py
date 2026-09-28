"""
Executes the actual AWS-side block/unblock action: a Network ACL deny rule
for a single flagged source IP, scoped to the subnet it lives in.

WHY A NACL AND NOT A SECURITY GROUP:
AWS Security Groups are allow-only -- there is no "deny" rule type. NACLs
are ordered, explicit allow/deny lists evaluated at the subnet boundary,
which is the correct AWS primitive for "block this one IP" without
touching any existing allow rules or other hosts' access.

AUTH:
This function calls AWS APIs from Azure, so it can't use an EC2 instance
role or the OIDC_ThinkiXSentinelRole (that role's trust policy is scoped
to Sentinel's own app registration/audience, not this Function App).
Instead it uses a dedicated, minimally-scoped IAM user's access keys,
stored as Function App secrets:
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_DEFAULT_REGION
That IAM user needs only: ec2:DescribeSubnets, ec2:DescribeNetworkAcls,
ec2:CreateNetworkAclEntry, ec2:DeleteNetworkAclEntry -- nothing else.
See the IAM policy in README.md for the exact document to attach.

ENDPOINTS (both POST, JSON body):
    /api/block_executor?action=block    {"sourceHost": "10.10.2.205", "confidence": 0.91, "reason": "..."}
    /api/block_executor?action=unblock  {"sourceHost": "10.10.2.205"}

Every block is recorded to Blob Storage (blocks/ prefix in the model
container) with a timestamp, so blocks are auditable and reversible --
this is also what satisfies the "unblock" side of the report's own note
about "assessments to determine when automatic block signals prohibit an
amplification" (i.e. blocks must be reviewable and reversible, not
one-way).
"""

import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
import boto3
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
VPC_ID = os.environ["TARGET_VPC_ID"]

STORAGE_ACCOUNT_URL = os.environ["MODEL_STORAGE_ACCOUNT_URL"]
CONTAINER_NAME = os.environ.get("MODEL_CONTAINER_NAME", "anomaly-models")

# NACL rule numbers 1-99 reserved for manual/Terraform-managed rules;
# automated blocks use 100-199, leaving headroom and avoiding collisions
# with anything already in place.
AUTO_BLOCK_RULE_NUMBER_START = 100
AUTO_BLOCK_RULE_NUMBER_END = 199


def _ec2_client():
    return boto3.client(
        "ec2",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def _blob_container():
    credential = DefaultAzureCredential()
    service = BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=credential)
    return service.get_container_client(CONTAINER_NAME)


def _find_nacl_for_ip(ec2, ip_address: str) -> tuple[str, list]:
    """Finds the NACL associated with the subnet that contains ip_address."""
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [VPC_ID]}])["Subnets"]

    import ipaddress

    target_subnet_id = None
    for subnet in subnets:
        if ipaddress.ip_address(ip_address) in ipaddress.ip_network(subnet["CidrBlock"]):
            target_subnet_id = subnet["SubnetId"]
            break

    if not target_subnet_id:
        raise ValueError(f"No subnet in {VPC_ID} contains {ip_address}")

    nacls = ec2.describe_network_acls(
        Filters=[{"Name": "association.subnet-id", "Values": [target_subnet_id]}]
    )["NetworkAcls"]

    if not nacls:
        raise ValueError(f"No NACL associated with subnet {target_subnet_id}")

    nacl = nacls[0]
    return nacl["NetworkAclId"], nacl["Entries"]


def _next_free_rule_number(existing_entries: list, egress: bool) -> int:
    used = {
        e["RuleNumber"]
        for e in existing_entries
        if e["Egress"] == egress and AUTO_BLOCK_RULE_NUMBER_START <= e["RuleNumber"] <= AUTO_BLOCK_RULE_NUMBER_END
    }
    for n in range(AUTO_BLOCK_RULE_NUMBER_START, AUTO_BLOCK_RULE_NUMBER_END + 1):
        if n not in used:
            return n
    raise RuntimeError("No free auto-block rule numbers left (100-199 all in use) -- manual cleanup needed")


def _record_block(source_host: str, nacl_id: str, rule_numbers: dict, confidence: float, reason: str) -> None:
    container = _blob_container()
    record = {
        "sourceHost": source_host,
        "naclId": nacl_id,
        "ruleNumbers": rule_numbers,
        "confidence": confidence,
        "reason": reason,
        "blockedAtUtc": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }
    blob_name = f"blocks/{source_host.replace('.', '-')}.json"
    container.upload_blob(name=blob_name, data=json.dumps(record, indent=2), overwrite=True)


def _get_block_record(source_host: str) -> dict | None:
    container = _blob_container()
    blob_name = f"blocks/{source_host.replace('.', '-')}.json"
    blob = container.get_blob_client(blob_name)
    if not blob.exists():
        return None
    return json.loads(blob.download_blob().readall())


def block_host(source_host: str, confidence: float, reason: str) -> dict:
    existing = _get_block_record(source_host)
    if existing and existing.get("status") == "active":
        logging.info(f"{source_host} already has an active block, skipping duplicate")
        return {"status": "already_blocked", "record": existing}

    ec2 = _ec2_client()
    nacl_id, entries = _find_nacl_for_ip(ec2, source_host)

    ingress_rule_num = _next_free_rule_number(entries, egress=False)
    egress_rule_num = _next_free_rule_number(entries + [{"RuleNumber": ingress_rule_num, "Egress": False}], egress=True)

    cidr = f"{source_host}/32"

    ec2.create_network_acl_entry(
        NetworkAclId=nacl_id,
        RuleNumber=ingress_rule_num,
        Protocol="-1",
        RuleAction="deny",
        Egress=False,
        CidrBlock=cidr,
    )
    ec2.create_network_acl_entry(
        NetworkAclId=nacl_id,
        RuleNumber=egress_rule_num,
        Protocol="-1",
        RuleAction="deny",
        Egress=True,
        CidrBlock=cidr,
    )

    rule_numbers = {"ingress": ingress_rule_num, "egress": egress_rule_num}
    _record_block(source_host, nacl_id, rule_numbers, confidence, reason)

    logging.warning(f"BLOCKED {source_host} via NACL {nacl_id} rules {rule_numbers} (confidence={confidence:.3f})")
    return {"status": "blocked", "naclId": nacl_id, "ruleNumbers": rule_numbers}


def unblock_host(source_host: str) -> dict:
    record = _get_block_record(source_host)
    if not record or record.get("status") != "active":
        return {"status": "not_blocked"}

    ec2 = _ec2_client()
    nacl_id = record["naclId"]
    rule_numbers = record["ruleNumbers"]

    ec2.delete_network_acl_entry(NetworkAclId=nacl_id, RuleNumber=rule_numbers["ingress"], Egress=False)
    ec2.delete_network_acl_entry(NetworkAclId=nacl_id, RuleNumber=rule_numbers["egress"], Egress=True)

    record["status"] = "unblocked"
    record["unblockedAtUtc"] = datetime.now(timezone.utc).isoformat()
    container = _blob_container()
    blob_name = f"blocks/{source_host.replace('.', '-')}.json"
    container.upload_blob(name=blob_name, data=json.dumps(record, indent=2), overwrite=True)

    logging.warning(f"UNBLOCKED {source_host} (NACL {nacl_id} rules {rule_numbers} removed)")
    return {"status": "unblocked"}


def main(req: func.HttpRequest) -> func.HttpResponse:
    action = req.params.get("action", "block")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "invalid or missing JSON body"}), status_code=400, mimetype="application/json")

    source_host = body.get("sourceHost")
    if not source_host:
        return func.HttpResponse(json.dumps({"error": "sourceHost is required"}), status_code=400, mimetype="application/json")

    try:
        if action == "block":
            result = block_host(source_host, body.get("confidence", 0.0), body.get("reason", ""))
        elif action == "unblock":
            result = unblock_host(source_host)
        else:
            return func.HttpResponse(json.dumps({"error": f"unknown action '{action}'"}), status_code=400, mimetype="application/json")
    except Exception as e:
        logging.exception(f"block_executor failed for {source_host}")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")

    return func.HttpResponse(json.dumps(result), status_code=200, mimetype="application/json")
