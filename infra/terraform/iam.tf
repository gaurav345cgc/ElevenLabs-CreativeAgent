data "aws_iam_policy_document" "composer_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "enhancer_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "composer" {
  name               = "${local.name_prefix}-composer-lambda"
  assume_role_policy = data.aws_iam_policy_document.composer_assume_role.json
}

resource "aws_iam_role" "enhancer" {
  name               = "${local.name_prefix}-enhancer-lambda"
  assume_role_policy = data.aws_iam_policy_document.enhancer_assume_role.json
}

data "aws_iam_policy_document" "composer_inline" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.composer.arn}:*",
    ]
  }

  statement {
    sid    = "ReadDatabaseSecret"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      aws_secretsmanager_secret.database.arn,
      aws_secretsmanager_secret.model_provider.arn,
    ]
  }

  statement {
    sid    = "PublishEnhancementJobs"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [aws_sqs_queue.enhancement.arn]
  }
}

data "aws_iam_policy_document" "enhancer_inline" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.enhancer.arn}:*",
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
      aws_secretsmanager_secret.model_provider.arn,
    ]
  }

  statement {
    sid    = "ConsumeEnhancementJobs"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.enhancement.arn]
  }
}

resource "aws_iam_role_policy" "composer" {
  name   = "${local.name_prefix}-composer"
  role   = aws_iam_role.composer.id
  policy = data.aws_iam_policy_document.composer_inline.json
}

resource "aws_iam_role_policy" "enhancer" {
  name   = "${local.name_prefix}-enhancer"
  role   = aws_iam_role.enhancer.id
  policy = data.aws_iam_policy_document.enhancer_inline.json
}

# Basic Lambda execution (non-VPC). Add VPC/network policies in a later phase if Aurora is private.
resource "aws_iam_role_policy_attachment" "composer_basic" {
  role       = aws_iam_role.composer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "composer_vpc" {
  count = local.lambda_network_enabled ? 1 : 0

  role       = aws_iam_role.composer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "enhancer_basic" {
  role       = aws_iam_role.enhancer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "enhancer_vpc" {
  count = local.lambda_network_enabled ? 1 : 0

  role       = aws_iam_role.enhancer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
