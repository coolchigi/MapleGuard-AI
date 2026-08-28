# MapleGuard infra

Terraform for the always-on monitor stack, with a Makefile for trivial tear-up/tear-down. You
run the apply; this just wraps it.

## What it creates
- **S3 bucket** — the agent session store (`MAPLEGUARD_SESSION_BUCKET`).
- **DynamoDB** — `mapleguard-profiles` (monitored profiles) and `mapleguard-snapshot` (the feed
  snapshot), both PAY_PER_REQUEST so there is no idle cost.
- **SNS topic** — user-facing alerts (`MAPLEGUARD_ALERT_TOPIC_ARN`); disable with
  `-var alerts_enabled=false`.
- **Lambda** — `agent.monitor_lambda.lambda_handler`, packaged from `../server` (pure core +
  boto3, no vendored deps).
- **EventBridge rule** — invokes the Lambda on `schedule_expression` (default every 6 hours).
  That unprompted, scheduled run is the autonomy.

Not here: **AgentCore Runtime** (the advisor) deploys via its own `agentcore` CLI, see
`docs/agentcore-runbook.md` section 6. Keeping it out of Terraform is deliberate.

## Use
```bash
cd infra
make aws-up            # terraform init + apply
make output            # table names / bucket / topic arn -> the MAPLEGUARD_* env vars
# ... seed the profiles table, watch the schedule run ...
make aws-down          # destroy everything (every resource is tagged Project=mapleguard)
```
Override defaults: `terraform apply -var region=us-west-2 -var 'schedule_expression=rate(1 hour)'`.

## Notes
- Requires AWS credentials with permission to create the above (an admin or a scoped deploy
  role). `make aws-down` relies on `force_destroy` (S3) and PAY_PER_REQUEST tables for a clean,
  instant sweep.
- The Lambda reads the LIVE IRCC rounds feed each run; no data is seeded by Terraform. Put
  monitored candidate profiles in the profiles table as `{"id": ..., "profile": {...}}` items
  (attribute `data` = that JSON), which `DynamoDBProfileStore` reads.
