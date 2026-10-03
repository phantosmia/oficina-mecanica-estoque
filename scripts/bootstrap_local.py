"""Cria no LocalStack os recursos de mensageria do Estoque (docker-compose).

Só para desenvolvimento local: na AWS, filas, DLQs, tópico e assinaturas são
criados pelo Terraform do serviço. Idempotente (criar fila/tópico que já
existe devolve o mesmo identificador).

- tópico `estoque-eventos` (onde o Estoque publica);
- fila `estoque-comandos` (comandos do orquestrador);
- fila `estoque-catalogo-eventos`, assinando o tópico `catalogo-eventos`
  (o tópico é criado aqui também, caso o Catálogo ainda não tenha subido).

Uso: `python -m scripts.bootstrap_local`
"""

import json
import logging

import boto3

from app.shared.settings import settings


def _queue_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def bootstrap(catalog_topic_name: str = "catalogo-eventos") -> dict[str, str]:
    sns = boto3.client("sns", region_name=settings.aws_region)
    sqs = boto3.client("sqs", region_name=settings.aws_region)

    events_topic = sns.create_topic(Name=settings.events_topic_arn.rsplit(":", 1)[-1])["TopicArn"]
    commands_queue = sqs.create_queue(QueueName=_queue_name(settings.commands_queue_url))["QueueUrl"]
    catalog_queue = sqs.create_queue(QueueName=_queue_name(settings.catalog_events_queue_url))["QueueUrl"]
    catalog_queue_arn = sqs.get_queue_attributes(QueueUrl=catalog_queue, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    catalog_topic = sns.create_topic(Name=catalog_topic_name)["TopicArn"]
    sqs.set_queue_attributes(
        QueueUrl=catalog_queue,
        Attributes={
            "Policy": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "sns.amazonaws.com"},
                            "Action": "sqs:SendMessage",
                            "Resource": catalog_queue_arn,
                            "Condition": {"ArnEquals": {"aws:SourceArn": catalog_topic}},
                        }
                    ],
                }
            )
        },
    )
    sns.subscribe(
        TopicArn=catalog_topic,
        Protocol="sqs",
        Endpoint=catalog_queue_arn,
        Attributes={"RawMessageDelivery": "true"},
        ReturnSubscriptionArn=True,
    )
    return {"events_topic": events_topic, "commands_queue": commands_queue, "catalog_queue": catalog_queue}


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("bootstrap").info("recursos locais prontos: %s", bootstrap())
