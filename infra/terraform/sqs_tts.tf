resource "aws_sqs_queue" "tts_audio_dlq" {
  name                      = "${local.name_prefix}-tts-audio-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "tts_audio" {
  name                       = "${local.name_prefix}-tts-audio"
  visibility_timeout_seconds = var.tts_sqs_visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 10
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.tts_audio_dlq.arn
    maxReceiveCount     = var.tts_sqs_max_receive_count
  })
}
