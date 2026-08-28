output "session_bucket" {
  description = "S3 bucket for the agent session store (set MAPLEGUARD_SESSION_BUCKET to this)."
  value       = aws_s3_bucket.sessions.bucket
}

output "profiles_table" {
  description = "DynamoDB table of monitored profiles (MAPLEGUARD_PROFILES_TABLE)."
  value       = aws_dynamodb_table.profiles.name
}

output "snapshot_table" {
  description = "DynamoDB table for the feed snapshot (MAPLEGUARD_SNAPSHOT_TABLE)."
  value       = aws_dynamodb_table.snapshot.name
}

output "alerts_topic_arn" {
  description = "SNS topic ARN for user-facing alerts (MAPLEGUARD_ALERT_TOPIC_ARN), if enabled."
  value       = var.alerts_enabled ? aws_sns_topic.alerts[0].arn : ""
}

output "monitor_function" {
  description = "The monitor Lambda function name."
  value       = aws_lambda_function.monitor.function_name
}

output "schedule" {
  description = "The EventBridge schedule expression driving the monitor."
  value       = aws_cloudwatch_event_rule.monitor.schedule_expression
}
