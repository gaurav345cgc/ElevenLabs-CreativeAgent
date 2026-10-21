locals {
  lambda_network_enabled = var.deploy_lambdas && var.lambda_vpc_id != "" && length(var.lambda_subnet_ids) > 0
}

resource "aws_security_group" "lambda" {
  count = local.lambda_network_enabled ? 1 : 0

  name        = "${local.name_prefix}-lambda"
  description = "Creative Agent Lambdas (${var.environment})"
  vpc_id      = var.lambda_vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "aurora_from_lambda" {
  count = local.lambda_network_enabled && var.aurora_security_group_id != "" ? 1 : 0

  description              = "PostgreSQL from Creative Agent Lambdas"
  ip_protocol              = "tcp"
  from_port                = 5432
  to_port                  = 5432
  security_group_id        = var.aurora_security_group_id
  referenced_security_group_id = aws_security_group.lambda[0].id
}

