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

.PHONY: aws-up aws-down plan fmt output init validate

init:
	$(TF) init

aws-up: init
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
