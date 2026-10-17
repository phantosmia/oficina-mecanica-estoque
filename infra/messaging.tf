# Mensageria do serviço (RFC-0007, contrato em docs/saga.md do
# oficina-mecanica-fiap): cada serviço cria o próprio tópico de eventos, a
# própria fila de comandos e as filas com que assina tópicos de outros
# serviços. Toda fila tem uma DLQ.

resource "aws_sns_topic" "events" {
  name = "${local.prefix}-estoque-eventos"
}

# Comandos do orquestrador da saga (OS Service). O OS Service envia pela
# API do SQS com a role dos nodes do EKS, na mesma conta: não precisa de
# queue policy.
resource "aws_sqs_queue" "commands_dlq" {
  name                      = "${local.prefix}-estoque-comandos-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "commands" {
  name = "${local.prefix}-estoque-comandos"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.commands_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# Assinatura do tópico de eventos do Catálogo, que precisa ter
# sido aplicado antes (ordem de apply em docs/arquitetura.md).
data "aws_sns_topic" "catalog_events" {
  name = "${local.prefix}-catalogo-eventos"
}

resource "aws_sqs_queue" "catalog_events_dlq" {
  name                      = "${local.prefix}-estoque-catalogo-eventos-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "catalog_events" {
  name = "${local.prefix}-estoque-catalogo-eventos"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.catalog_events_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

data "aws_iam_policy_document" "catalog_events" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.catalog_events.arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [data.aws_sns_topic.catalog_events.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "catalog_events" {
  queue_url = aws_sqs_queue.catalog_events.id
  policy    = data.aws_iam_policy_document.catalog_events.json
}

# Entrega crua (sem o envelope do SNS), como no docker-compose.
resource "aws_sns_topic_subscription" "catalog_events" {
  topic_arn            = data.aws_sns_topic.catalog_events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.catalog_events.arn
  raw_message_delivery = true

  depends_on = [aws_sqs_queue_policy.catalog_events]
}
