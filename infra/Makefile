# MapleGuard infra — trivial tear-up / tear-down of the monitor stack (S3 + DynamoDB + SNS +
# Lambda + EventBridge schedule). AgentCore Runtime is separate (docs/agentcore-runbook.md).
#
# The user runs the actual apply/destroy; these are the wrappers.
#   make aws-up      init + apply (stand everything up)
#   make aws-down    destroy (tear everything down; every resource is tagged for a clean sweep)
#   make plan        show the plan without applying
#   make fmt         terraform fmt
#   make output      show outputs (table names, bucket, topic arn) for the env vars
#   make kb-up       provision the Bedrock KB on S3 Vectors (NOT Terraform, see kb/ script)

TF ?= terraform

.PHONY: aws-up aws-down plan fmt output init validate api-package kb-up

# Build the API Lambda package (deps as linux/x86_64 wheels + server source) into build/api_pkg/.
# Required before apply when api_enabled=true (the default). Skipped by `make plan`/`validate`.
api-package:
	bash build-api.sh

init:
	$(TF) init

aws-up: init api-package
	$(TF) apply -auto-approve

plan: init
	$(TF) plan

aws-down:
	$(TF) destroy -auto-approve

# Provision the Bedrock Knowledge Base on S3 Vectors. Terraform cannot (no provider support), so
# this runs the boto3 script in kb/. Credentialed: wrap with the vault the way you run aws-up.
#   aws-vault exec terraform-dev --no-session -- make kb-up
kb-up:
	cd ../server && PYTHONPATH=. python3 ../infra/kb/provision_s3_vectors_kb.py

fmt:
	$(TF) fmt -recursive

validate: init
	$(TF) validate

output:
	$(TF) output
