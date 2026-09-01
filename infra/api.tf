# The FastAPI API as a Lambda behind a public Function URL — the backend the web frontend calls.
#
# Coherent with the monitor: both are Lambdas in this one Terraform, no container/ECR. The API
# Lambda shares the SAME profiles DynamoDB table the monitor reads, so a profile saved through
# POST /profiles is a profile the monitor watches. `make api-package` builds build/api_pkg/ (deps
# as linux/x86_64 wheels + server source) before apply; `make aws-up` runs it for you.

locals {
  # A `us.` cross-region inference profile needs InvokeModel on BOTH the profile ARN and the
  # underlying foundation-model ARN in every region it can route to.
  bedrock_base_model = trimprefix(var.bedrock_model_id, "us.")
  bedrock_invoke_resources = [
    "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
    "arn:aws:bedrock:us-east-1::foundation-model/${local.bedrock_base_model}",
    "arn:aws:bedrock:us-east-2::foundation-model/${local.bedrock_base_model}",
    "arn:aws:bedrock:us-west-2::foundation-model/${local.bedrock_base_model}",
  ]
}

data "archive_file" "api" {
  count       = var.api_enabled ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/build/api_pkg" # produced by `make api-package` (build-api.sh)
  output_path = "${path.module}/build/api_lambda.zip"
}

resource "aws_iam_role" "api" {
  count = var.api_enabled ? 1 : 0
  name  = "${local.name}-api-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  count      = var.api_enabled ? 1 : 0
  role       = aws_iam_role.api[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api" {
  count = var.api_enabled ? 1 : 0
  name  = "${local.name}-api-policy"
  role  = aws_iam_role.api[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read/write the monitored-profile table (POST/GET /profiles) — the store the monitor lists.
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan"]
        Resource = [aws_dynamodb_table.profiles.arn]
      },
      {
        # Invoke the pinned Bedrock model for the /audit + /draft NOC steps.
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.bedrock_invoke_resources
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  count            = var.api_enabled ? 1 : 0
  function_name    = "${local.name}-api"
  role             = aws_iam_role.api[0].arn
  handler          = "api.lambda_handler.handler"
  runtime          = "python3.12"
  architectures    = ["x86_64"] # matches the manylinux2014_x86_64 wheels build-api.sh installs
  timeout          = 30
  memory_size      = 512
  filename         = data.archive_file.api[0].output_path
  source_code_hash = data.archive_file.api[0].output_base64sha256

  environment {
    variables = {
      # Share the monitor's profile table so intake and the watch loop are one store.
      MAPLEGUARD_PROFILES_TABLE = aws_dynamodb_table.profiles.name
      # NOC audit/draft on Bedrock with the runtime role's creds (no ANTHROPIC_API_KEY).
      MAPLEGUARD_NOC_BACKEND   = "bedrock"
      MAPLEGUARD_BEDROCK_MODEL = var.bedrock_model_id
    }
  }
}

resource "aws_lambda_function_url" "api" {
  count              = var.api_enabled ? 1 : 0
  function_name      = aws_lambda_function.api[0].function_name
  authorization_type = "NONE" # public read/compute API; no secrets (Bedrock via the role)

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
  }
}
