variable "region" {
  description = "AWS region for all MapleGuard resources."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project tag / name prefix. Everything is named and tagged with this so tear-down is clean."
  type        = string
  default     = "mapleguard"
}

variable "schedule_expression" {
  description = "How often the monitor Lambda runs (EventBridge rate/cron). Default: every 6 hours."
  type        = string
  default     = "rate(6 hours)"
}

variable "alerts_enabled" {
  description = "Create the SNS topic and wire it to the monitor so alerts are published (not just logged)."
  type        = bool
  default     = true
}

variable "rounds_url" {
  description = "Optional override of the IRCC rounds feed URL (defaults to ingest.ROUNDS_JSON_URL in code)."
  type        = string
  default     = ""
}
