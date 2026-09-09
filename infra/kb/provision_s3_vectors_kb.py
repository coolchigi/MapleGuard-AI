#!/usr/bin/env python3
"""Stand up the MapleGuard Knowledge Base on Amazon S3 Vectors, end to end, in one command.

Why this is a script and not Terraform: the Terraform AWS provider has no S3 Vectors support
(hashicorp/terraform-provider-aws issues #43438 / #44871 / #45395), so `make aws-up` deliberately
does NOT create the KB. This script is the credentialed counterpart the project lead runs.

What it does, idempotently (re-running skips anything that already exists):
  1. Build the cited corpus from the source-verified NOC 2021 records (agent.write_kb_corpus).
  2. Create a regular S3 bucket for the corpus documents and upload the .txt + .metadata.json pairs.
  3. Create an S3 *vectors* bucket + index (this is where embeddings live; separate from step 2).
  4. Create (or reuse) the IAM role Bedrock assumes to read the docs, embed them, and write vectors.
  5. Create the Bedrock Knowledge Base on the S3 Vectors index, add the S3 data source, and start
     the ingestion job.
  6. Print the KB id and the exact env exports to wire onto the API Lambda + AgentCore runtime.

The boto3 shapes here are verified against current AWS docs (Sept 2026): the S3 Vectors API
(create_vector_bucket / create_index) and bedrock-agent create_knowledge_base with
storageConfiguration.type = "S3_VECTORS". The API is new; if a field name has since changed, the
error will name it, fix it here rather than guessing.

Run it (the lead runs the credentialed command):

    cd server && PYTHONPATH=. python3 ../infra/kb/provision_s3_vectors_kb.py
    # or, with the project's vault:
    aws-vault exec terraform-dev --no-session -- \
        bash -c 'cd server && PYTHONPATH=. python3 ../infra/kb/provision_s3_vectors_kb.py'

Prereqs: Titan Text Embeddings V2 must be enabled in Bedrock model access for the region, and the
caller needs permissions for s3, s3vectors, bedrock-agent, and (for step 4) iam. If IAM role
creation is denied, pass an existing role ARN with --role-arn and the script skips step 4.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# The corpus builder lives in server/agent. Make it importable whether or not PYTHONPATH is set.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "server"))

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    sys.exit("boto3 is required: pip install boto3")

# Titan Text Embeddings V2 at 1024 dims. The KB config and the vector index dimension MUST match.
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 1024
# AMAZON_BEDROCK_TEXT is the reserved key Bedrock writes the chunk text under; it must be
# non-filterable in the index. Our own citation keys (source, noc_code, ...) stay filterable.
RESERVED_TEXT_KEY = "AMAZON_BEDROCK_TEXT"


def _log(step: str, msg: str) -> None:
    print(f"[{step}] {msg}", flush=True)


def _already_exists(err: ClientError) -> bool:
    code = err.response.get("Error", {}).get("Code", "")
    return code in {
        "ConflictException", "BucketAlreadyOwnedByYou", "BucketAlreadyExists",
        "ResourceInUseException", "EntityAlreadyExists",
    }


def build_and_upload_corpus(s3, region: str, docs_bucket: str, prefix: str) -> int:
    """Steps 1-2: build the corpus and upload it to a regular S3 bucket under `prefix`."""
    from agent import write_kb_corpus  # imported here so --help works without server deps

    corpus_dir = _REPO_ROOT / "infra" / "kb" / "corpus"
    n = write_kb_corpus(str(corpus_dir))
    _log("corpus", f"built {n} cited passages into {corpus_dir}")

    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=docs_bucket)  # us-east-1 rejects a LocationConstraint
        else:
            s3.create_bucket(Bucket=docs_bucket,
                             CreateBucketConfiguration={"LocationConstraint": region})
        _log("s3", f"created docs bucket {docs_bucket}")
    except ClientError as err:
        if not _already_exists(err):
            raise
        _log("s3", f"docs bucket {docs_bucket} already exists, reusing")

    uploaded = 0
    for f in sorted(corpus_dir.iterdir()):
        # Only the real corpus pair. Skip macOS AppleDouble shadows (._foo) and anything else, or
        # Bedrock ingests the ._ resource-fork blobs as garbage documents.
        if not f.is_file() or f.name.startswith("._"):
            continue
        if not (f.name.endswith(".txt") or f.name.endswith(".metadata.json")):
            continue
        s3.upload_file(str(f), docs_bucket, f"{prefix}/{f.name}")
        uploaded += 1
    _log("s3", f"uploaded {uploaded} files to s3://{docs_bucket}/{prefix}/")
    return n


def ensure_vector_index(s3v, vector_bucket: str, index_name: str) -> str:
    """Step 3: create the S3 vectors bucket + index. Returns the index ARN."""
    try:
        s3v.create_vector_bucket(vectorBucketName=vector_bucket)
        _log("s3vectors", f"created vector bucket {vector_bucket}")
    except ClientError as err:
        if not _already_exists(err):
            raise
        _log("s3vectors", f"vector bucket {vector_bucket} already exists, reusing")

    try:
        resp = s3v.create_index(
            vectorBucketName=vector_bucket,
            indexName=index_name,
            dimension=EMBED_DIM,
            distanceMetric="cosine",
            dataType="float32",
            metadataConfiguration={"nonFilterableMetadataKeys": [RESERVED_TEXT_KEY]},
        )
        index_arn = resp["indexArn"]
        _log("s3vectors", f"created index {index_name}")
    except ClientError as err:
        if not _already_exists(err):
            raise
        index_arn = s3v.get_index(vectorBucketName=vector_bucket, indexName=index_name)[
            "index"]["indexArn"]
        _log("s3vectors", f"index {index_name} already exists, reusing")
    return index_arn


def ensure_kb_role(iam, account: str, region: str, role_name: str,
                   docs_bucket: str, index_arn: str) -> str:
    """Step 4: create (or reuse) the role Bedrock assumes for ingestion. Returns the role ARN.

    Scoped tight: embed only with the Titan model, read only the corpus bucket, write vectors only
    to this index. If the caller lacks IAM permissions, this raises — pass --role-arn to skip it.
    """
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    perms = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel"],
             "Resource": f"arn:aws:bedrock:{region}::foundation-model/{EMBED_MODEL}"},
            {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetObject"],
             "Resource": [f"arn:aws:s3:::{docs_bucket}", f"arn:aws:s3:::{docs_bucket}/*"]},
            # Bedrock KB ingestion + retrieval needs the full s3vectors data plane on the index,
            # not just query/put: it reads (GetVectors), lists, and deletes stale vectors on
            # re-ingestion. GetVectors missing is the ValidationException create_knowledge_base
            # raises. GetVectorBucket is the bucket-level describe it also checks.
            {"Effect": "Allow",
             "Action": ["s3vectors:GetIndex", "s3vectors:ListVectors", "s3vectors:GetVectors",
                        "s3vectors:PutVectors", "s3vectors:QueryVectors", "s3vectors:DeleteVectors"],
             "Resource": index_arn},
            {"Effect": "Allow", "Action": ["s3vectors:GetVectorBucket"],
             "Resource": index_arn.split("/index/")[0]},
        ],
    }
    try:
        iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust),
                        Description="MapleGuard Bedrock KB ingestion role (S3 Vectors)")
        _log("iam", f"created role {role_name}")
    except ClientError as err:
        if not _already_exists(err):
            raise
        _log("iam", f"role {role_name} already exists, reusing")
    iam.put_role_policy(RoleName=role_name, PolicyName="mapleguard-kb-ingest",
                        PolicyDocument=json.dumps(perms))
    _log("iam", "attached scoped ingestion policy")
    # A freshly created role is not immediately assumable by Bedrock; give IAM a moment to settle.
    time.sleep(10)
    return f"arn:aws:iam::{account}:role/{role_name}"


def ensure_knowledge_base(bedrock, region: str, kb_name: str, role_arn: str,
                          index_arn: str) -> str:
    resp = bedrock.create_knowledge_base(
        name=kb_name,
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn":
                    f"arn:aws:bedrock:{region}::foundation-model/{EMBED_MODEL}",
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": EMBED_DIM,
                        "embeddingDataType": "FLOAT32",
                    }
                },
            },
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {"indexArn": index_arn},
        },
    )
    kb_id = resp["knowledgeBase"]["knowledgeBaseId"]
    _log("kb", f"created knowledge base {kb_id}")
    return kb_id


def ensure_data_source_and_ingest(bedrock, kb_id: str, docs_bucket: str, prefix: str,
                                  account: str) -> None:
    ds_name = "mapleguard-noc-corpus"
    # Reuse the data source by name if it already exists, so a re-run re-ingests the same source
    # instead of piling up duplicate data sources on the KB.
    existing = next((d for d in bedrock.list_data_sources(knowledgeBaseId=kb_id)
                     .get("dataSourceSummaries", []) if d.get("name") == ds_name), None)
    if existing:
        ds_id = existing["dataSourceId"]
        _log("kb", f"data source {ds_id} already exists, reusing")
    else:
        resp = bedrock.create_data_source(
            knowledgeBaseId=kb_id,
            name=ds_name,
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{docs_bucket}",
                    "inclusionPrefixes": [f"{prefix}/"],
                },
            },
            # Our passages are already one-idea-per-file (a lead statement or a single duty), so a
            # generous fixed chunk keeps each cited passage intact rather than splitting a citation.
            vectorIngestionConfiguration={
                "chunkingConfiguration": {
                    "chunkingStrategy": "FIXED_SIZE",
                    "fixedSizeChunkingConfiguration": {"maxTokens": 512, "overlapPercentage": 10},
                }
            },
        )
        ds_id = resp["dataSource"]["dataSourceId"]
        _log("kb", f"created data source {ds_id}")
    job = bedrock.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    _log("kb", f"started ingestion job {job['ingestionJob']['ingestionJobId']} "
               "(watch it in the Bedrock console; retrieval is live once it completes)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision the MapleGuard KB on S3 Vectors.")
    ap.add_argument("--region", default=None, help="AWS region (default: session region or us-east-1)")
    ap.add_argument("--prefix", default="mapleguard", help="resource name prefix")
    ap.add_argument("--role-arn", default=None,
                    help="existing Bedrock KB role ARN; skips IAM role creation (step 4)")
    args = ap.parse_args()

    session = boto3.session.Session()
    region = args.region or session.region_name or "us-east-1"
    account = boto3.client("sts").get_caller_identity()["Account"]
    _log("start", f"account {account}, region {region}")

    docs_bucket = f"{args.prefix}-kb-corpus-{account}"
    vector_bucket = f"{args.prefix}-kb-vectors-{account}"
    index_name = f"{args.prefix}-noc-index"
    role_name = f"{args.prefix}-kb-ingest-role"
    kb_name = f"{args.prefix}-noc-kb"
    doc_prefix = "corpus"

    s3 = boto3.client("s3", region_name=region)
    s3v = boto3.client("s3vectors", region_name=region)
    iam = boto3.client("iam")
    bedrock = boto3.client("bedrock-agent", region_name=region)

    build_and_upload_corpus(s3, region, docs_bucket, doc_prefix)
    index_arn = ensure_vector_index(s3v, vector_bucket, index_name)

    role_arn = args.role_arn
    if role_arn is None:
        role_arn = ensure_kb_role(iam, account, region, role_name, docs_bucket, index_arn)

    kb_id = ensure_knowledge_base(bedrock, region, kb_name, role_arn, index_arn)
    ensure_data_source_and_ingest(bedrock, kb_id, docs_bucket, doc_prefix, account)

    print("\n" + "=" * 68)
    print("KB provisioned. Wire it on the API Lambda and the AgentCore runtime:")
    print(f"  export MAPLEGUARD_MEMORY_BACKEND=bedrock_kb")
    print(f"  export MAPLEGUARD_KB_ID={kb_id}")
    print(f"  export MAPLEGUARD_KB_REGION={region}")
    print("Re-run this script whenever the NOC corpus grows (it re-uploads + re-ingests).")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
