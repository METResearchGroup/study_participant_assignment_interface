output "user_assignments_table_name" {
  description = "DynamoDB table name for user assignments."
  value       = aws_dynamodb_table.user_assignments.name
}

output "user_assignments_table_arn" {
  description = "DynamoDB table ARN for user assignments."
  value       = aws_dynamodb_table.user_assignments.arn
}

output "study_assignment_counter_table_name" {
  description = "DynamoDB table name for study assignment counters."
  value       = aws_dynamodb_table.study_assignment_counter.name
}

output "study_assignment_counter_table_arn" {
  description = "DynamoDB table ARN for study assignment counters."
  value       = aws_dynamodb_table.study_assignment_counter.arn
}

output "ecr_repository_url" {
  description = "ECR repository URL for the get_study_assignment image (account.dkr.ecr.region.amazonaws.com/repo)."
  value       = aws_ecr_repository.get_study_assignment.repository_url
}

output "ecr_repository_name" {
  description = "ECR repository name for get_study_assignment."
  value       = aws_ecr_repository.get_study_assignment.name
}

output "lambda_function_name" {
  description = "Deployed get_study_assignment Lambda function name."
  value       = aws_lambda_function.get_study_assignment.function_name
}

output "lambda_function_arn" {
  description = "Deployed get_study_assignment Lambda function ARN."
  value       = aws_lambda_function.get_study_assignment.arn
}
