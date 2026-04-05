variable "lambda_image_uri" {
  description = "Full ECR image URI (tag or digest) for the get_study_assignment container image. Required when creating or updating the Lambda."
  type        = string
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
