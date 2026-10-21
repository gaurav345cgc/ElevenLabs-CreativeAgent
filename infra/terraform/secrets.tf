resource "aws_secretsmanager_secret" "database" {
  name        = "${local.name_prefix}/database"
  description = "Creative Agent Aurora PostgreSQL credentials (${var.environment})"
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = var.db_secret_username
    password = var.db_secret_password
    host     = var.db_host
    port     = var.db_port
    dbname   = var.db_name
    engine   = "postgres"
    # SQLAlchemy / psycopg2 URL for Lambdas
    database_url = "postgresql://${var.db_secret_username}:${var.db_secret_password}@${var.db_host}:${var.db_port}/${var.db_name}?sslmode=require"
  })
}

resource "aws_secretsmanager_secret" "model_provider" {
  name        = "${local.name_prefix}/model-provider"
  description = "LLM / model provider API keys (${var.environment})"
}

resource "aws_secretsmanager_secret_version" "model_provider" {
  count = var.model_provider_api_key != "" ? 1 : 0

  secret_id = aws_secretsmanager_secret.model_provider.id
  secret_string = jsonencode({
    api_key = var.model_provider_api_key
  })
}

resource "aws_secretsmanager_secret" "elevenlabs" {
  name        = "${local.name_prefix}/elevenlabs"
  description = "ElevenLabs TTS API key (${var.environment})"
}

resource "aws_secretsmanager_secret_version" "elevenlabs" {
  count = var.elevenlabs_api_key != "" ? 1 : 0

  secret_id = aws_secretsmanager_secret.elevenlabs.id
  secret_string = jsonencode({
    api_key            = var.elevenlabs_api_key
    elevenlabs_api_key = var.elevenlabs_api_key
  })
}
