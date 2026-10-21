variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment name: dev, staging, production"
  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be dev, staging, or production"
  }
}

variable "project_name" {
  type        = string
  description = "Resource name prefix"
  default     = "creative-agent"
}

# Existing Aurora dev cluster (created manually). Terraform manages net-new infra only.
variable "aurora_cluster_identifier" {
  type        = string
  description = "Existing Aurora cluster identifier for documentation/outputs"
  default     = ""
}

variable "db_secret_username" {
  type        = string
  description = "Database master/application username for Secrets Manager"
  sensitive   = true
}

variable "db_secret_password" {
  type        = string
  description = "Database password for Secrets Manager"
  sensitive   = true
}

variable "db_host" {
  type        = string
  description = "Aurora writer or instance endpoint hostname"
}

variable "db_name" {
  type        = string
  description = "Database name"
  default     = "creative_agent"
}

variable "db_port" {
  type        = number
  description = "Database port"
  default     = 5432
}

variable "model_provider_api_key" {
  type        = string
  description = "Optional LLM provider API key (empty to skip model secret version)"
  default     = ""
  sensitive   = true
}

variable "sqs_visibility_timeout_seconds" {
  type        = number
  description = "Must exceed max Lambda 2 runtime"
  default     = 960
}

variable "sqs_max_receive_count" {
  type        = number
  description = "Retries before message moves to DLQ"
  default     = 3
}

variable "queue_depth_alarm_threshold" {
  type        = number
  description = "Alarm when visible messages exceed this count"
  default     = 100
}

variable "queue_age_alarm_seconds" {
  type        = number
  description = "Alarm when oldest message age exceeds this (seconds)"
  default     = 600
}

variable "composer_lambda_function_name" {
  type        = string
  description = "Legacy: external Agent 1 Lambda name for alarms when deploy_lambdas=false"
  default     = ""
}

variable "enhancer_lambda_function_name" {
  type        = string
  description = "Legacy: external Agent 2 Lambda name when deploy_lambdas=false"
  default     = ""
}

variable "deploy_lambdas" {
  type        = bool
  description = "Create Lambda functions from infra/terraform/build/lambda.zip"
  default     = true
}

variable "api_key" {
  type        = string
  description = "Intake API key (X-API-Key). Empty disables API key checks."
  default     = ""
  sensitive   = true
}

variable "lambda_script_generator" {
  type        = string
  description = "CREATIVE_AGENT_SCRIPT_GENERATOR for Lambdas: auto, openai, or template"
  default     = "auto"
}

variable "lambda_transcript_validator" {
  type        = string
  description = "CREATIVE_AGENT_TRANSCRIPT_VALIDATOR for Lambdas: auto, openai, or rules"
  default     = "rules"
}

variable "composer_lambda_timeout_seconds" {
  type        = number
  description = "Agent 1 Lambda timeout"
  default     = 300
}

variable "composer_lambda_memory_mb" {
  type        = number
  description = "Agent 1 Lambda memory (MB)"
  default     = 512
}

variable "enhancer_lambda_timeout_seconds" {
  type        = number
  description = "Agent 2 Lambda timeout (must be less than sqs_visibility_timeout_seconds)"
  default     = 900
}

variable "enhancer_lambda_memory_mb" {
  type        = number
  description = "Agent 2 Lambda memory (MB)"
  default     = 1024
}

variable "api_lambda_timeout_seconds" {
  type        = number
  description = "Intake API Lambda timeout"
  default     = 300
}

variable "api_lambda_memory_mb" {
  type        = number
  description = "Intake API Lambda memory (MB)"
  default     = 512
}

variable "api_cors_allow_origins" {
  type        = list(string)
  description = "CORS allowed origins for API Function URL"
  default     = ["*"]
}

variable "lambda_vpc_id" {
  type        = string
  description = "VPC id for Lambda ENIs"
  default     = ""
}

variable "lambda_subnet_ids" {
  type        = list(string)
  description = "Subnet ids for Lambda ENIs"
  default     = []
}

variable "aurora_security_group_id" {
  type        = string
  description = "Security group id attached to Aurora (PostgreSQL) cluster/instance"
  default     = ""
}

variable "enhancer_lambda_batch_size" {
  type        = number
  description = "SQS messages per Lambda 2 invocation"
  default     = 1
}

variable "enhancer_lambda_maximum_batching_window_seconds" {
  type        = number
  description = "Max wait time to gather SQS batch"
  default     = 0
}

variable "enhancer_lambda_max_concurrency" {
  type        = number
  description = "Maximum concurrent Lambda 2 invocations from SQS"
  default     = 5
}

variable "enhancer_sqs_trigger_enabled" {
  type        = bool
  description = "Attach SQS queue to Agent 2 Lambda"
  default     = true
}

variable "enable_rds_proxy" {
  type        = bool
  description = "Phase 3 decision: off for dev until Lambda concurrency grows"
  default     = false
}

variable "tts_audio_bucket_force_destroy" {
  type        = bool
  description = "Allow Terraform to empty and delete the TTS audio bucket on destroy (dev only)"
  default     = false
}

variable "tts_audio_versioning_enabled" {
  type        = bool
  description = "Enable S3 versioning on the TTS audio bucket"
  default     = false
}

variable "tts_debug_object_expiration_days" {
  type        = number
  description = "Days until debug-tagged TTS objects expire (artifact_kind=debug)"
  default     = 90
}

variable "tts_audio_kms_key_arn" {
  type        = string
  description = "Optional CMK for TTS audio bucket SSE-KMS; empty uses SSE-S3 (AES256)"
  default     = ""
}

variable "tts_job_created_hourly_alarm_threshold" {
  type        = number
  description = "CloudWatch alarm when JobCreated sum exceeds this value in one hour"
  default     = 50
}

variable "elevenlabs_api_key" {
  type        = string
  description = "ElevenLabs TTS API key for worker Lambda"
  default     = ""
  sensitive   = true
}

variable "tts_lambda_timeout_seconds" {
  type        = number
  description = "TTS worker Lambda timeout (must be less than tts_sqs_visibility_timeout_seconds)"
  default     = 900
}

variable "tts_lambda_memory_mb" {
  type        = number
  description = "TTS worker Lambda memory (MB)"
  default     = 1024
}

variable "tts_lambda_ephemeral_storage_mb" {
  type        = number
  description = "TTS worker Lambda /tmp size (MB). FFmpeg stitch + background mix needs headroom beyond default 512."
  default     = 2048
}

variable "tts_sqs_visibility_timeout_seconds" {
  type        = number
  description = "Must exceed TTS worker Lambda timeout"
  default     = 960
}

variable "tts_sqs_max_receive_count" {
  type        = number
  description = "TTS queue retries before message moves to DLQ"
  default     = 3
}

variable "tts_sqs_trigger_enabled" {
  type        = bool
  description = "Attach TTS audio queue to worker Lambda"
  default     = true
}

variable "tts_lambda_batch_size" {
  type        = number
  description = "SQS messages per TTS worker invocation"
  default     = 1
}

variable "tts_lambda_maximum_batching_window_seconds" {
  type        = number
  description = "Max wait time to gather TTS SQS batch"
  default     = 0
}

variable "tts_lambda_max_concurrency" {
  type        = number
  description = "Maximum concurrent TTS worker invocations from SQS"
  default     = 2
}
