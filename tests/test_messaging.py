"""Ponta a ponta com SQS/SNS simulados (moto): fila → worker → banco →
outbox → relay → tópico → fila de quem assina (o orquestrador)."""

import json

import boto3
import pytest

from app.messaging.dispatcher import Dispatcher, parse_body
from app.messaging.sqs_consumer import SqsConsumer
from app.shared.database import get_session_factory
from app.shared.outbox import OutboxRelay
from app.shared.settings import settings
from app.shared.sns_publisher import SnsEventPublisher
from tests.conftest import add_stock, command_msg, outbox, stock_of

sqs = lambda: boto3.client("sqs", region_name="us-east-1")  # noqa: E731
sns = lambda: boto3.client("sns", region_name="us-east-1")  # noqa: E731


@pytest.fixture
def orchestrator_queue() -> str:
    """Fila assinando o tópico do Estoque, como a `os-saga-eventos` do OS Service."""
    url = sqs().create_queue(QueueName="os-saga-eventos")["QueueUrl"]
    arn = sqs().get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns().subscribe(TopicArn=settings.events_topic_arn, Protocol="sqs", Endpoint=arn, Attributes={"RawMessageDelivery": "true"})
    return url


@pytest.fixture
def consumer(dispatcher: Dispatcher) -> SqsConsumer:
    return SqsConsumer([settings.commands_queue_url, settings.catalog_events_queue_url], dispatcher, wait_seconds=0)


def queue_size(url: str) -> int:
    attrs = sqs().get_queue_attributes(
        QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


def test_command_round_trip(consumer: SqsConsumer, orchestrator_queue: str) -> None:
    add_stock("oleo", 10)
    command = command_msg("ReservarPecas", saga_id="saga-xyz", order_id=7, items=[{"part_id": "oleo", "quantity": 2}])
    sqs().send_message(QueueUrl=settings.commands_queue_url, MessageBody=json.dumps(command.to_dict()))

    assert consumer.poll_once() == 1
    assert queue_size(settings.commands_queue_url) == 0
    assert stock_of("oleo").reserved == 2

    relay = OutboxRelay(get_session_factory(), SnsEventPublisher(settings.events_topic_arn))
    assert relay.run_once() == 1
    assert relay.run_once() == 0

    received = sqs().receive_message(QueueUrl=orchestrator_queue, MessageAttributeNames=["All"])["Messages"]
    assert len(received) == 1
    reply = json.loads(received[0]["Body"])
    assert reply["type"] == "PecasReservadas"
    attributes = {k: v["StringValue"] for k, v in received[0]["MessageAttributes"].items()}
    assert attributes == {"type": "PecasReservadas", "saga_id": "saga-xyz", "correlation_id": "saga-xyz", "order_id": "7"}


def test_part_registered_arrives_from_catalog_topic(consumer: SqsConsumer) -> None:
    """O Catálogo publica no tópico dele; a fila do Estoque assina esse tópico."""
    catalog_topic = sns().create_topic(Name="catalogo-eventos")["TopicArn"]
    event = {
        "message_id": "m-1", "type": "PecaCadastrada", "saga_id": None, "order_id": None,
        "occurred_at": "2026-10-03T12:00:00+00:00", "payload": {"part_id": "pneu", "sku": "PNEU-15", "name": "Pneu aro 15"},
    }
    sns().publish(TopicArn=catalog_topic, Message=json.dumps(event))

    assert consumer.poll_once() == 1
    assert stock_of("pneu").name == "Pneu aro 15"


def test_malformed_message_stays_in_queue(consumer: SqsConsumer) -> None:
    sqs().send_message(QueueUrl=settings.commands_queue_url, MessageBody="isto não é json")

    assert consumer.poll_once() == 0
    assert queue_size(settings.commands_queue_url) == 1  # volta a ficar visível e, depois de 5 tentativas, vai pra DLQ


def test_technical_failure_keeps_message_for_retry(consumer: SqsConsumer, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, envelope):  # noqa: ANN001, ARG001
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(Dispatcher, "handle", boom)
    sqs().send_message(QueueUrl=settings.commands_queue_url, MessageBody=json.dumps(command_msg("LiberarPecas").to_dict()))

    assert consumer.poll_once() == 0
    assert queue_size(settings.commands_queue_url) == 1


def test_unknown_type_is_removed_from_queue(consumer: SqsConsumer) -> None:
    sqs().send_message(QueueUrl=settings.commands_queue_url, MessageBody=json.dumps(command_msg("Desconhecido").to_dict()))

    assert consumer.poll_once() == 1
    assert outbox() == []


def test_parse_body_accepts_sns_notification_wrapper() -> None:
    inner = command_msg("PecaCadastrada", part_id="p").to_dict()
    wrapped = json.dumps({"Type": "Notification", "Message": json.dumps(inner)})

    assert parse_body(wrapped).to_dict() == inner
