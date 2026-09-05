# Bedrock Guardrail for PII redaction on stored reference letters.
#
# Reference letters carry real personal data (candidate and signatory names, contact details).
# The API Lambda already runs each letter through ApplyGuardrail on write (see api/guardrail.py),
# so with this guardrail in place no raw PII lands in DynamoDB. Gated on api_enabled because the
# API is the only thing that applies it. Managed here so it stands up and tears down with the rest
# of the stack via make aws-up / make aws-down.

resource "aws_bedrock_guardrail" "pii" {
  count                     = var.api_enabled ? 1 : 0
  name                      = "${local.name}-pii"
  description               = "Redacts PII from stored MapleGuard reference letters."
  blocked_input_messaging   = "This input was blocked by the MapleGuard guardrail."
  blocked_outputs_messaging = "This output was blocked by the MapleGuard guardrail."

  # ANONYMIZE masks each detected entity (e.g. {NAME}) rather than blocking the whole request, so
  # the letter is still usable for the NOC audit while the personal data is gone.
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "NAME"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
  }
}

# A published, immutable version so the Lambda pins a stable guardrail instead of the mutable DRAFT.
resource "aws_bedrock_guardrail_version" "pii" {
  count         = var.api_enabled ? 1 : 0
  guardrail_arn = aws_bedrock_guardrail.pii[0].guardrail_arn
  description   = "MapleGuard PII redaction, managed by terraform."
}

output "guardrail_id" {
  description = "Bedrock Guardrail id the API Lambda applies to scrub reference-letter PII."
  value       = var.api_enabled ? aws_bedrock_guardrail.pii[0].guardrail_id : null
}

output "guardrail_version" {
  description = "Published guardrail version the API Lambda pins."
  value       = var.api_enabled ? aws_bedrock_guardrail_version.pii[0].version : null
}
