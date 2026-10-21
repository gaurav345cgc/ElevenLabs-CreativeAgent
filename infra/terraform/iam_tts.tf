# IAM for TTS plane workers (SQS consumer Lambda).

data "aws_iam_policy_document" "tts_pipeline_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tts_pipeline" {
  name               = "${local.name_prefix}-tts-pipeline-lambda"
  assume_role_policy = data.aws_iam_policy_document.tts_pipeline_assume_role.json
}

data "aws_iam_policy_document" "tts_pipeline_inline" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.tts_worker.arn}:*",
    ]
  }

  statement {
    sid    = "ReadSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      aws_secretsmanager_secret.database.arn,
      aws_secretsmanager_secret.elevenlabs.arn,
    ]
  }

  statement {
    sid    = "ConsumeTtsJobs"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.tts_audio.arn]
  }

  statement {
    sid    = "ListTtsAudioBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.tts_audio.arn]
  }

  statement {
    sid    = "ReadWriteTtsAudioObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.tts_audio.arn}/*"]
  }

  dynamic "statement" {
    for_each = var.tts_audio_kms_key_arn != "" ? [1] : []
    content {
      sid    = "UseTtsAudioKmsKey"
      effect = "Allow"
      actions = [
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey",
      ]
      resources = [var.tts_audio_kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "tts_pipeline" {
  name   = "${local.name_prefix}-tts-pipeline"
  role   = aws_iam_role.tts_pipeline.id
  policy = data.aws_iam_policy_document.tts_pipeline_inline.json
}

resource "aws_iam_role_policy_attachment" "tts_pipeline_basic" {
  role       = aws_iam_role.tts_pipeline.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "tts_pipeline_vpc" {
  count = local.lambda_network_enabled ? 1 : 0

  role       = aws_iam_role.tts_pipeline.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
