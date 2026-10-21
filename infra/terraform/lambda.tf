# Agent 2 SQS consumer wiring.

resource "aws_lambda_event_source_mapping" "enhancer_sqs" {
  count = var.deploy_lambdas && var.enhancer_sqs_trigger_enabled ? 1 : (
    var.enhancer_sqs_trigger_enabled && var.enhancer_lambda_function_name != "" ? 1 : 0
  )

  event_source_arn = aws_sqs_queue.enhancement.arn
  function_name = var.deploy_lambdas ? aws_lambda_function.enhancer[0].arn : var.enhancer_lambda_function_name
  enabled       = true

  batch_size                         = var.enhancer_lambda_batch_size
  maximum_batching_window_in_seconds = var.enhancer_lambda_maximum_batching_window_seconds
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.enhancer_lambda_max_concurrency
  }
}

resource "aws_lambda_event_source_mapping" "tts_worker_sqs" {
  count = var.deploy_lambdas && var.tts_sqs_trigger_enabled ? 1 : 0

  event_source_arn = aws_sqs_queue.tts_audio.arn
  function_name    = aws_lambda_function.tts_worker[0].arn
  enabled          = true

  batch_size                         = var.tts_lambda_batch_size
  maximum_batching_window_in_seconds = var.tts_lambda_maximum_batching_window_seconds
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.tts_lambda_max_concurrency
  }
}
