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
