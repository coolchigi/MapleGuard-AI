# AWS monthly cost budget — the early-warning half of the cost guardrail.
#
# This ALERTS, it does not cap. The hard cap is `reserved_concurrent_executions` on the API Lambda
# (see api.tf). Together: the concurrency reservation bounds worst-case spend, and this budget warns
# you as actual spend climbs toward the monthly limit.
#
# Notifications are created only when `budget_alert_email` is set. With no email the budget still
# exists and tracks spend in the console, it just warns no one, so nothing here can fail an apply
# on a fresh account.

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly-cost"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.budget_alert_email != "" ? [50, 80, 100] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
