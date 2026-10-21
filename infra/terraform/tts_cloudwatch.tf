# TTS plane — CloudWatch log group, dashboard, and alarms.
# Metrics are emitted via EMF JSON logs (observability/tts.py) under namespace CreativeAgent/TTS.

resource "aws_cloudwatch_log_group" "tts_pipeline" {
  name              = "/creative-agent/${var.environment}/tts"
  retention_in_days = 30
}

resource "aws_cloudwatch_dashboard" "tts" {
  dashboard_name = "${local.name_prefix}-tts"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "TTS job throughput"
          region = var.aws_region
          metrics = [
            ["CreativeAgent/TTS", "JobCreated", { stat = "Sum", label = "Created" }],
            [".", "JobCompleted", { stat = "Sum", label = "Completed" }],
            [".", "JobFailed", { stat = "Sum", label = "Failed" }],
            [".", "JobPartiallyFailed", { stat = "Sum", label = "Partially failed" }],
            [".", "JobReviewRequired", { stat = "Sum", label = "Review required" }],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "TTS chunk health"
          region = var.aws_region
          metrics = [
            ["CreativeAgent/TTS", "ChunkCompleted", { stat = "Sum", label = "Completed" }],
            [".", "ChunkFailed", { stat = "Sum", label = "Failed" }],
            [".", "ChunkRetry", { stat = "Sum", label = "Retries" }],
            [".", "ChunkSkipped", { stat = "Sum", label = "Skipped" }],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ElevenLabs provider latency (ms)"
          region = var.aws_region
          metrics = [
            ["CreativeAgent/TTS", "ProviderLatencyMs", { stat = "Average", label = "Avg" }],
            ["...", { stat = "p99", label = "p99" }],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "TTS infrastructure failures"
          region = var.aws_region
          metrics = [
            ["CreativeAgent/TTS", "StorageFailure", { stat = "Sum", label = "Storage" }],
            [".", "DbWriteFailure", { stat = "Sum", label = "DB write" }],
            [".", "WorkflowFailed", { stat = "Sum", label = "Workflow" }],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "TTS finalization"
          region = var.aws_region
          metrics = [
            ["CreativeAgent/TTS", "ManifestFinalized", { stat = "Sum", label = "Manifest" }],
            [".", "FinalMerged", { stat = "Sum", label = "Final merged" }],
            [".", "WorkflowSucceeded", { stat = "Sum", label = "Workflow OK" }],
          ]
          period = 300
          view   = "timeSeries"
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "tts_job_failures" {
  alarm_name          = "${local.name_prefix}-tts-job-failures"
  alarm_description   = "TTS jobs failing or requiring review"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "failures"
    expression  = "m1 + m2"
    label       = "Job failures + review required"
    return_data = true
  }

  metric_query {
    id = "m1"
    metric {
      metric_name = "JobFailed"
      namespace   = "CreativeAgent/TTS"
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id = "m2"
    metric {
      metric_name = "JobReviewRequired"
      namespace   = "CreativeAgent/TTS"
      period      = 300
      stat        = "Sum"
    }
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "tts_chunk_failures" {
  alarm_name          = "${local.name_prefix}-tts-chunk-failures"
  alarm_description   = "TTS chunk synthesis failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ChunkFailed"
  namespace           = "CreativeAgent/TTS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "tts_partial_failures" {
  alarm_name          = "${local.name_prefix}-tts-partial-failures"
  alarm_description   = "Repeated TTS partial job failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "JobPartiallyFailed"
  namespace           = "CreativeAgent/TTS"
  period              = 300
  statistic           = "Sum"
  threshold           = 2
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "tts_provider_latency" {
  alarm_name          = "${local.name_prefix}-tts-provider-latency"
  alarm_description   = "ElevenLabs synthesis latency is abnormally high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ProviderLatencyMs"
  namespace           = "CreativeAgent/TTS"
  period              = 300
  extended_statistic  = "p99"
  threshold           = 120000
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "tts_job_created_spike" {
  alarm_name          = "${local.name_prefix}-tts-job-created-spike"
  alarm_description   = "Unusual TTS job creation rate (cost guardrail)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "JobCreated"
  namespace           = "CreativeAgent/TTS"
  period              = 3600
  statistic           = "Sum"
  threshold           = var.tts_job_created_hourly_alarm_threshold
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
}
