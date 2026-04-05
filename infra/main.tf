terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
  }
}

variable "aws_region" {
  description = "AWS region for DynamoDB tables."
  type        = string
  default     = "us-east-2"
}

provider "aws" {
  region = var.aws_region
}

resource "aws_dynamodb_table" "user_assignments" {
  name         = "user_assignments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "study_id"
  range_key    = "iteration_user_key"

  attribute {
    name = "study_id"
    type = "S"
  }

  attribute {
    name = "iteration_user_key"
    type = "S"
  }
}

resource "aws_dynamodb_table" "study_assignment_counter" {
  name         = "study_assignment_counter"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "study_id"
  range_key    = "iteration_assignment_key"

  attribute {
    name = "study_id"
    type = "S"
  }

  attribute {
    name = "iteration_assignment_key"
    type = "S"
  }
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_iam_policy_document" "get_study_assignment_lambda_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

data "aws_iam_policy_document" "get_study_assignment_lambda_execution" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.lambda_function_name}",
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.lambda_function_name}:*",
    ]
  }

  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem",
    ]
    resources = [
      aws_dynamodb_table.user_assignments.arn,
      aws_dynamodb_table.study_assignment_counter.arn,
    ]
  }

  statement {
    sid    = "S3ListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.s3_assignments_bucket_name}",
    ]
  }

  statement {
    sid    = "S3GetObject"
    effect = "Allow"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.s3_assignments_bucket_name}/*",
    ]
  }
}

resource "aws_ecr_repository" "get_study_assignment" {
  name                 = var.ecr_repository_name
  image_tag_mutability = var.ecr_image_tag_mutability

  image_scanning_configuration {
    scan_on_push = var.ecr_scan_on_push
  }
}

locals {
  lambda_image_uri_effective = coalesce(
    var.lambda_image_uri,
    "${aws_ecr_repository.get_study_assignment.repository_url}:${var.lambda_image_tag}"
  )
}

resource "aws_iam_role" "get_study_assignment_lambda" {
  name               = "${var.lambda_function_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.get_study_assignment_lambda_assume.json
}

resource "aws_iam_role_policy" "get_study_assignment_lambda" {
  name   = "dynamodb-s3-logs"
  role   = aws_iam_role.get_study_assignment_lambda.id
  policy = data.aws_iam_policy_document.get_study_assignment_lambda_execution.json
}

resource "aws_lambda_function" "get_study_assignment" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.get_study_assignment_lambda.arn
  package_type  = "Image"
  image_uri     = local.lambda_image_uri_effective

  memory_size = var.lambda_memory_size

  environment {
    variables = {
      user_assignments_table_name         = aws_dynamodb_table.user_assignments.name
      study_assignment_counter_table_name = aws_dynamodb_table.study_assignment_counter.name
      region_name                         = var.aws_region
    }
  }
}
