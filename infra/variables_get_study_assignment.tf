variable "lambda_image_uri" {
  description = "Optional full ECR image URI (tag or digest). If null, the Lambda uses aws_ecr_repository.repository_url + \":\" + lambda_image_tag."
  type        = string
  default     = null
  nullable    = true
}

variable "lambda_image_tag" {
  description = "Image tag when lambda_image_uri is null (e.g. latest)."
  type        = string
  default     = "latest"
}

variable "lambda_function_name" {
  description = "Lambda function name for get_study_assignment."
  type        = string
  default     = "get_study_assignment"
}

variable "ecr_repository_name" {
  description = "ECR repository name for the get_study_assignment image."
  type        = string
  default     = "get_study_assignment"
}

variable "s3_assignments_bucket_name" {
  description = "S3 bucket name for assignment parquet reads (IAM only until handler uses env)."
  type        = string
  default     = "jspsych-mirror-view-3"
}

variable "lambda_memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 512
}

variable "ecr_image_tag_mutability" {
  description = "ECR tag mutability (MUTABLE or IMMUTABLE)."
  type        = string
  default     = "MUTABLE"
}

variable "ecr_scan_on_push" {
  description = "Enable ECR image scanning on push."
  type        = bool
  default     = true
}
