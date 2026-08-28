# MapleGuard monitor infrastructure — S3 (session store) + DynamoDB (profiles + snapshot) +
# SNS (alerts) + Lambda (the monitor) + EventBridge schedule (the autonomy).
#
# AgentCore Runtime is deliberately NOT here: it deploys via its own `agentcore` CLI (see
# docs/agentcore-runbook.md section 6). This file is everything else, so `make aws-up` /
# `make aws-down` gives the user trivial tear-up/tear-down of the always-on pieces.

data "aws_caller_identity" "current" {}

locals {
  name = var.project
}

# --------------------------------------------------------------------- session store (S3)
resource "aws_s3_bucket" "sessions" {
  bucket        = "${local.name}-sessions-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # so `make aws-down` removes it even with stored sessions
}

resource "aws_s3_bucket_public_access_block" "sessions" {
  bucket                  = aws_s3_bucket.sessions.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ----------------------------------------------------------------- profiles + snapshot (DynamoDB)
resource "aws_dynamodb_table" "profiles" {
  name         = "${local.name}-profiles"
  billing_mode = "PAY_PER_REQUEST" # no idle cost; destroy is instant
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "snapshot" {
  name         = "${local.name}-snapshot"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# ------------------------------------------------------------------------- alerts (SNS)
resource "aws_sns_topic" "alerts" {
  count = var.alerts_enabled ? 1 : 0
  name  = "${local.name}-alerts"
}

# ------------------------------------------------------------- Lambda package (the monitor)
# Zip the server/ tree, minus tests, the web-only api, caches, and docker/build files. The
# handler needs only the pure core + boto3 (provided by the Lambda runtime), so no vendored deps.
data "archive_file" "monitor" {
  type        = "zip"
  source_dir  = "${path.module}/../server"
  output_path = "${path.module}/build/monitor_lambda.zip"

  excludes = [
    "tests", "api", "scripts", "Dockerfile", "requirements.txt",
    "__pycache__", "agent/__pycache__", "crs/__pycache__", "pnp/__pycache__",
    "paths/__pycache__", "noc/__pycache__", "ingest/__pycache__",
  ]
}

# --------------------------------------------------------------------- Lambda IAM role
resource "aws_iam_role" "monitor" {
  name = "${local.name}-monitor-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.monitor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "monitor" {
  name = "${local.name}-monitor-policy"
  role = aws_iam_role.monitor.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.profiles.arn,
          aws_dynamodb_table.snapshot.arn,
        ]
      }
      ], var.alerts_enabled ? [{
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.alerts[0].arn]
    }] : [])
  })
}

# ------------------------------------------------------------------------- Lambda function
resource "aws_lambda_function" "monitor" {
  function_name    = "${local.name}-monitor"
  role             = aws_iam_role.monitor.arn
  handler          = "agent.monitor_lambda.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  filename         = data.archive_file.monitor.output_path
  source_code_hash = data.archive_file.monitor.output_base64sha256

  environment {
    variables = merge({
      MAPLEGUARD_PROFILES_TABLE = aws_dynamodb_table.profiles.name
      MAPLEGUARD_SNAPSHOT_TABLE = aws_dynamodb_table.snapshot.name
      },
      var.alerts_enabled ? { MAPLEGUARD_ALERT_TOPIC_ARN = aws_sns_topic.alerts[0].arn } : {},
      var.rounds_url != "" ? { MAPLEGUARD_ROUNDS_URL = var.rounds_url } : {},
    )
  }
}

# ------------------------------------------------------- EventBridge schedule (the autonomy)
resource "aws_cloudwatch_event_rule" "monitor" {
  name                = "${local.name}-monitor-schedule"
  description         = "Runs the MapleGuard monitor Lambda on a cadence with no prompt."
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "monitor" {
  rule = aws_cloudwatch_event_rule.monitor.name
  arn  = aws_lambda_function.monitor.arn
}

resource "aws_lambda_permission" "events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.monitor.arn
}
