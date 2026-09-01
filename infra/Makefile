# MapleGuard infra — trivial tear-up / tear-down of the monitor stack (S3 + DynamoDB + SNS +
# Lambda + EventBridge schedule). AgentCore Runtime is separate (docs/agentcore-runbook.md).
#
# The user runs the actual apply/destroy; these are the wrappers.
#   make aws-up      init + apply (stand everything up)
#   make aws-down    destroy (tear everything down; every resource is tagged for a clean sweep)
#   make plan        show the plan without applying
#   make fmt         terraform fmt
#   make output      show outputs (table names, bucket, topic arn) for the env vars

TF ?= terraform

.PHONY: aws-up aws-down plan fmt output init validate api-package

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

fmt:
	$(TF) fmt -recursive

validate: init
	$(TF) validate

output:
	$(TF) output
