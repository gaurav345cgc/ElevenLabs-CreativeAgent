# Shared Lambda configuration and function resources.
# Run scripts/build_lambda_package.py before terraform apply (produces lambda-composer.zip, lambda-enhancer.zip, lambda-api.zip).

locals {
  lambda_composer_package = "${path.module}/build/lambda-composer.zip"
  lambda_enhancer_package = "${path.module}/build/lambda-enhancer.zip"
  lambda_api_package      = "${path.module}/build/lambda-api.zip"

  lambda_database_url = "postgresql://${var.db_secret_username}:${var.db_secret_password}@${var.db_host}:${var.db_port}/${var.db_name}?sslmode=require&connect_timeout=8"

  lambda_common_env = {
    CREATIVE_AGENT_ENV                       = var.environment
    CREATIVE_AGENT_AWS_REGION                = var.aws_region
    CREATIVE_AGENT_DB_SECRET_ARN             = aws_secretsmanager_secret.database.arn
    CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN = aws_secretsmanager_secret.model_provider.arn
    CREATIVE_AGENT_SCRIPT_GENERATOR          = var.lambda_script_generator
    CREATIVE_AGENT_TRANSCRIPT_VALIDATOR      = var.lambda_transcript_validator
    # Also inject direct values so Lambdas don't block on Secrets Manager networking.
    CREATIVE_AGENT_DATABASE_URL              = local.lambda_database_url
    CREATIVE_AGENT_OPENAI_API_KEY            = var.model_provider_api_key
  }

  lambda_composer_env = merge(local.lambda_common_env, {
    CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL = aws_sqs_queue.enhancement.url
  })

  lambda_api_env = merge(local.lambda_composer_env, {
    CREATIVE_AGENT_API_KEY          = var.api_key
    CREATIVE_AGENT_TTS_AUDIO_BUCKET = aws_s3_bucket.tts_audio.id
    CREATIVE_AGENT_TTS_QUEUE_URL    = aws_sqs_queue.tts_audio.url
  })

  lambda_enhancer_env = local.lambda_common_env
}

resource "aws_lambda_function" "composer" {
  count = var.deploy_lambdas ? 1 : 0

  function_name = "${local.name_prefix}-composer"
  role          = aws_iam_role.composer.arn
  handler       = "transcript_composer.handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  filename         = local.lambda_composer_package
  source_code_hash = filebase64sha256(local.lambda_composer_package)

  timeout     = var.composer_lambda_timeout_seconds
  memory_size = var.composer_lambda_memory_mb

  dynamic "vpc_config" {
    for_each = local.lambda_network_enabled ? [1] : []
    content {
      subnet_ids         = var.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda[0].id]
    }
  }

  environment {
    variables = local.lambda_composer_env
  }

  depends_on = [
    aws_cloudwatch_log_group.composer,
    aws_iam_role_policy.composer,
    aws_iam_role_policy_attachment.composer_basic,
  ]
}

resource "aws_lambda_function" "enhancer" {
  count = var.deploy_lambdas ? 1 : 0

  function_name = "${local.name_prefix}-enhancer"
  role          = aws_iam_role.enhancer.arn
  handler       = "tts_enhancer.handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  filename         = local.lambda_enhancer_package
  source_code_hash = filebase64sha256(local.lambda_enhancer_package)

  timeout     = var.enhancer_lambda_timeout_seconds
  memory_size = var.enhancer_lambda_memory_mb

  dynamic "vpc_config" {
    for_each = local.lambda_network_enabled ? [1] : []
    content {
      subnet_ids         = var.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda[0].id]
    }
  }

  environment {
    variables = local.lambda_enhancer_env
  }

  depends_on = [
    aws_cloudwatch_log_group.enhancer,
    aws_iam_role_policy.enhancer,
    aws_iam_role_policy_attachment.enhancer_basic,
  ]
}

resource "aws_lambda_function" "api" {
  count = var.deploy_lambdas ? 1 : 0

  function_name = "${local.name_prefix}-api"
  role          = aws_iam_role.api.arn
  handler       = "api.handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  filename         = local.lambda_api_package
  source_code_hash = filebase64sha256(local.lambda_api_package)

  timeout     = var.api_lambda_timeout_seconds
  memory_size = var.api_lambda_memory_mb

  dynamic "vpc_config" {
    for_each = local.lambda_network_enabled ? [1] : []
    content {
      subnet_ids         = var.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda[0].id]
    }
  }

  environment {
    variables = local.lambda_api_env
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy.api,
    aws_iam_role_policy_attachment.api_basic,
  ]
}

resource "aws_lambda_function_url" "api" {
  count = var.deploy_lambdas ? 1 : 0

  function_name      = aws_lambda_function.api[0].function_name
  authorization_type = "NONE"

  cors {
    allow_origins = var.api_cors_allow_origins
    allow_methods = ["*"]
    allow_headers = ["*"]
    max_age       = 300
  }
}
