output "environment" {
  value = var.environment
}

output "enhancement_queue_url" {
  value       = aws_sqs_queue.enhancement.url
  description = "Set CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL"
}

output "enhancement_queue_arn" {
  value = aws_sqs_queue.enhancement.arn
}

output "enhancement_dlq_url" {
  value = aws_sqs_queue.enhancement_dlq.url
}

output "enhancement_dlq_arn" {
  value = aws_sqs_queue.enhancement_dlq.arn
}

output "database_secret_arn" {
  value       = aws_secretsmanager_secret.database.arn
  description = "Set CREATIVE_AGENT_DB_SECRET_ARN"
}

output "model_provider_secret_arn" {
  value = aws_secretsmanager_secret.model_provider.arn
}

output "composer_lambda_role_arn" {
  value = aws_iam_role.composer.arn
}

output "enhancer_lambda_role_arn" {
  value = aws_iam_role.enhancer.arn
}

output "api_lambda_role_arn" {
  value = aws_iam_role.api.arn
}

output "composer_log_group" {
  value = aws_cloudwatch_log_group.composer.name
}

output "enhancer_log_group" {
  value = aws_cloudwatch_log_group.enhancer.name
}

output "api_log_group" {
  value = aws_cloudwatch_log_group.api.name
}

output "composer_lambda_function_name" {
  value       = try(aws_lambda_function.composer[0].function_name, null)
  description = "Agent 1 Lambda name"
}

output "enhancer_lambda_function_name" {
  value       = try(aws_lambda_function.enhancer[0].function_name, null)
  description = "Agent 2 Lambda name"
}

output "api_lambda_function_name" {
  value       = try(aws_lambda_function.api[0].function_name, null)
  description = "Intake API Lambda name"
}

output "api_function_url" {
  value       = try(aws_lambda_function_url.api[0].function_url, null)
  description = "Lambda Function URL (may be blocked by account public-access settings)"
}

output "api_gateway_url" {
  value       = try(aws_apigatewayv2_api.api[0].api_endpoint, null)
  description = "HTTP API base URL (append /health, /transcripts, etc.)"
}

output "alarms_sns_topic_arn" {
  value       = aws_sns_topic.alarms.arn
  description = "Subscribe email/Slack for operational alerts"
}

output "aurora_cluster_identifier" {
  value       = var.aurora_cluster_identifier
  description = "Existing Aurora cluster (managed outside this stack if pre-provisioned)"
}

output "enhancer_sqs_trigger_enabled" {
  value = (
    var.deploy_lambdas && var.enhancer_sqs_trigger_enabled
  ) || (
    var.enhancer_sqs_trigger_enabled && var.enhancer_lambda_function_name != ""
  )
  description = "Whether SQS event source mapping is active for Agent 2"
}

output "sqs_visibility_timeout_seconds" {
  value       = var.sqs_visibility_timeout_seconds
  description = "Must exceed enhancer Lambda timeout when trigger is enabled"
}

output "sqs_max_receive_count" {
  value = var.sqs_max_receive_count
}

output "rds_proxy_enabled" {
  value = var.enable_rds_proxy
}

output "tts_audio_bucket_name" {
  value       = aws_s3_bucket.tts_audio.id
  description = "Set CREATIVE_AGENT_TTS_AUDIO_BUCKET"
}

output "tts_audio_bucket_arn" {
  value = aws_s3_bucket.tts_audio.arn
}

output "tts_pipeline_lambda_role_arn" {
  value       = aws_iam_role.tts_pipeline.arn
  description = "IAM role for TTS plane worker Lambda"
}

output "tts_audio_queue_url" {
  value       = aws_sqs_queue.tts_audio.url
  description = "Set CREATIVE_AGENT_TTS_QUEUE_URL for local intake"
}

output "tts_audio_queue_arn" {
  value = aws_sqs_queue.tts_audio.arn
}

output "tts_audio_dlq_url" {
  value = aws_sqs_queue.tts_audio_dlq.url
}

output "tts_worker_lambda_function_name" {
  value       = try(aws_lambda_function.tts_worker[0].function_name, null)
  description = "TTS worker Lambda name"
}

output "elevenlabs_secret_arn" {
  value       = aws_secretsmanager_secret.elevenlabs.arn
  description = "Set CREATIVE_AGENT_ELEVENLABS_SECRET_ARN"
}
