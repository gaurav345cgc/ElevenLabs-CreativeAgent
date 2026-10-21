# TTS plane worker Lambda (SQS consumer — full orchestrator workflow).

locals {
  lambda_tts_package = "${path.module}/build/lambda-tts.zip"

  lambda_tts_env = merge(local.lambda_common_env, {
    CREATIVE_AGENT_TTS_AUDIO_BUCKET     = aws_s3_bucket.tts_audio.id
    CREATIVE_AGENT_ELEVENLABS_SECRET_ARN  = aws_secretsmanager_secret.elevenlabs.arn
    CREATIVE_AGENT_ELEVENLABS_API_KEY     = var.elevenlabs_api_key
    CREATIVE_AGENT_FFMPEG_PATH            = "/var/task/bin/ffmpeg"
  })
}

resource "aws_cloudwatch_log_group" "tts_worker" {
  name              = "/aws/lambda/${local.name_prefix}-tts-worker"
  retention_in_days = 30
}

resource "aws_lambda_function" "tts_worker" {
  count = var.deploy_lambdas ? 1 : 0

  function_name = "${local.name_prefix}-tts-worker"
  role          = aws_iam_role.tts_pipeline.arn
  handler       = "tts_pipeline.handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  filename         = local.lambda_tts_package
  source_code_hash = filebase64sha256(local.lambda_tts_package)

  timeout     = var.tts_lambda_timeout_seconds
  memory_size = var.tts_lambda_memory_mb

  ephemeral_storage {
    size = var.tts_lambda_ephemeral_storage_mb
  }

  dynamic "vpc_config" {
    for_each = local.lambda_network_enabled ? [1] : []
    content {
      subnet_ids         = var.lambda_subnet_ids
      security_group_ids = [aws_security_group.lambda[0].id]
    }
  }

  environment {
    variables = local.lambda_tts_env
  }

  depends_on = [
    aws_cloudwatch_log_group.tts_worker,
    aws_iam_role_policy.tts_pipeline,
    aws_iam_role_policy_attachment.tts_pipeline_basic,
    aws_iam_role_policy_attachment.tts_pipeline_vpc,
  ]
}
