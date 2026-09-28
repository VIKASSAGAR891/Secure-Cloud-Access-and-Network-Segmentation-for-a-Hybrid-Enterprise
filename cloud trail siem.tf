# --------------------------------------------------------------------
# AWS CloudTrail -> S3 -> SQS pipeline, feeding Microsoft Sentinel's
# AWS S3 connector for the SIEM pipeline. Management events only
# (free tier - no per-event CloudTrail charge). Sentinel polls the SQS
# queue for new-object notifications, then pulls the corresponding
# log file from S3.
# --------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# --- S3 bucket that CloudTrail writes logs into ---
resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket = "thinkix-cloudtrail-logs-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = "ThinkiX-ZeroTrust"
    Purpose = "CloudTrail-to-Sentinel"
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail_logs" {
  bucket                  = aws_s3_bucket.cloudtrail_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rule to auto-expire old logs after 90 days, keeping storage
# cost near-zero indefinitely rather than growing unbounded.
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  rule {
    id     = "expire-old-cloudtrail-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

# Bucket policy allowing the CloudTrail service to write logs here.
resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail_logs.arn
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      }
    ]
  })
}

# --- CloudTrail trail itself: management events only (free tier) ---
resource "aws_cloudtrail" "thinkix_trail" {
  name                          = "thinkix-management-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  event_selector {
    read_write_type           = "All"
    include_management_events = true
    # No data_resource blocks = data events (S3 object-level, Lambda
    # invocation logging) stay OFF - this is the setting that keeps
    # volume (and cost) near-zero. Do not add data_resource blocks
    # without discussing cost impact first.
  }

  tags = {
    Project = "ThinkiX-ZeroTrust"
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail_logs]
}

# --- SQS queue that Sentinel polls for new-log notifications ---
resource "aws_sqs_queue" "cloudtrail_notifications" {
  name                       = "thinkix-cloudtrail-sentinel-queue"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4 days

  tags = {
    Project = "ThinkiX-ZeroTrust"
  }
}

# Queue policy allowing the S3 bucket to publish notifications into it.
resource "aws_sqs_queue_policy" "cloudtrail_notifications" {
  queue_url = aws_sqs_queue.cloudtrail_notifications.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3Publish"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.cloudtrail_notifications.arn
        Condition = {
          ArnEquals = { "aws:SourceArn" = aws_s3_bucket.cloudtrail_logs.arn }
        }
      }
    ]
  })
}

# S3 -> SQS event notification: fires whenever CloudTrail writes a new
# log file, so Sentinel knows to go fetch it.
resource "aws_s3_bucket_notification" "cloudtrail_to_sqs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  queue {
    queue_arn     = aws_sqs_queue.cloudtrail_notifications.arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".gz"
  }

  depends_on = [aws_sqs_queue_policy.cloudtrail_notifications]
}

output "cloudtrail_bucket_name" {
  value = aws_s3_bucket.cloudtrail_logs.id
}

output "cloudtrail_sqs_queue_arn" {
  value = aws_sqs_queue.cloudtrail_notifications.arn
}
