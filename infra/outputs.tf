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
