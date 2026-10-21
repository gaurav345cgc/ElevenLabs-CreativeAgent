# TTS plane — audio artifact bucket (Phase 3).

locals {
  tts_audio_bucket_name = "${local.name_prefix}-tts-audio-${data.aws_caller_identity.current.account_id}"
  tts_sse_algorithm       = var.tts_audio_kms_key_arn != "" ? "aws:kms" : "AES256"
}

resource "aws_s3_bucket" "tts_audio" {
  bucket        = local.tts_audio_bucket_name
  force_destroy = var.tts_audio_bucket_force_destroy

  tags = {
    Name    = local.tts_audio_bucket_name
    Plane   = "tts"
    Purpose = "audio-artifacts"
  }
}

resource "aws_s3_bucket_public_access_block" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id

  versioning_configuration {
    status = var.tts_audio_versioning_enabled ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.tts_sse_algorithm
      kms_master_key_id = var.tts_audio_kms_key_arn != "" ? var.tts_audio_kms_key_arn : null
    }
    bucket_key_enabled = var.tts_audio_kms_key_arn != "" ? true : null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id

  rule {
    id     = "expire-debug-metadata"
    status = "Enabled"

    filter {
      tag {
        key   = "artifact_kind"
        value = "debug"
      }
    }

    expiration {
      days = var.tts_debug_object_expiration_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "tts_audio_bucket_deny_insecure_transport" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.tts_audio.arn,
      "${aws_s3_bucket.tts_audio.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tts_audio" {
  bucket = aws_s3_bucket.tts_audio.id
  policy = data.aws_iam_policy_document.tts_audio_bucket_deny_insecure_transport.json
}
