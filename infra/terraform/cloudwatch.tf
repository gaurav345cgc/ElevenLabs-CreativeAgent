resource "aws_cloudwatch_log_group" "composer" {
  name              = "/aws/lambda/${local.name_prefix}-composer"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "enhancer" {
  name              = "/aws/lambda/${local.name_prefix}-enhancer"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = 30
}

resource "aws_sns_topic" "alarms" {
  name = "${local.name_prefix}-alarms"
}

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${local.name_prefix}-enhancement-queue-depth"
  alarm_description   = "Enhancement queue backlog is growing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = var.queue_depth_alarm_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.enhancement.name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name          = "${local.name_prefix}-enhancement-queue-age"
  alarm_description   = "Oldest enhancement queue message is too old"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.queue_age_alarm_seconds
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.enhancement.name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${local.name_prefix}-enhancement-dlq-not-empty"
  alarm_description   = "Messages landed in enhancement DLQ"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.enhancement_dlq.name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "composer_errors" {
  count = var.deploy_lambdas ? 1 : (var.composer_lambda_function_name != "" ? 1 : 0)

  alarm_name          = "${local.name_prefix}-composer-errors"
  alarm_description   = "Agent 1 Lambda errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.deploy_lambdas ? aws_lambda_function.composer[0].function_name : var.composer_lambda_function_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "enhancer_errors" {
  count = var.deploy_lambdas ? 1 : (var.enhancer_lambda_function_name != "" ? 1 : 0)

  alarm_name          = "${local.name_prefix}-enhancer-errors"
  alarm_description   = "Agent 2 Lambda errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.deploy_lambdas ? aws_lambda_function.enhancer[0].function_name : var.enhancer_lambda_function_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  count = var.deploy_lambdas ? 1 : 0

  alarm_name          = "${local.name_prefix}-api-errors"
  alarm_description   = "Intake API Lambda errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.api[0].function_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "tts_worker_errors" {
  count = var.deploy_lambdas ? 1 : 0

  alarm_name          = "${local.name_prefix}-tts-worker-errors"
  alarm_description   = "TTS worker Lambda errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.tts_worker[0].function_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}
