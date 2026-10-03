"""Processo consumidor das filas do Estoque (`python -m app.worker`):
comandos da saga (`estoque-comandos`) e eventos do Catálogo
(`estoque-catalogo-eventos`)."""

import logging
import threading

from app.messaging.dispatcher import Dispatcher
from app.messaging.sqs_consumer import SqsConsumer
from app.shared.database import get_session_factory
from app.shared.logging_config import configure_logging
from app.shared.settings import settings
from app.stock.adapters.sqlalchemy_uow import SqlAlchemyStockUnitOfWork

logger = logging.getLogger("app.worker")


def _consume_forever(consumer: SqsConsumer, queue_url: str) -> None:  # pragma: no cover
    while True:
        try:
            consumer.poll_queue(queue_url)
        except Exception:
            logger.exception("falha ao ler a fila %s; tentando de novo", queue_url)


def main() -> None:  # pragma: no cover - laço infinito; a lógica testada fica em SqsConsumer/Dispatcher
    configure_logging(settings.log_level)
    dispatcher = Dispatcher(lambda: SqlAlchemyStockUnitOfWork(get_session_factory()))
    consumer = SqsConsumer([settings.commands_queue_url, settings.catalog_events_queue_url], dispatcher, settings.worker_wait_seconds)
    # Uma thread por fila: com uma só, o *long polling* numa fila vazia
    # atrasaria em até WORKER_WAIT_SECONDS as mensagens da outra.
    threads = [
        threading.Thread(target=_consume_forever, args=(consumer, url), name=f"sqs-{url.rsplit('/', 1)[-1]}", daemon=True)
        for url in consumer.queue_urls
    ]
    for thread in threads:
        thread.start()
    logger.info("worker iniciado filas=%s", consumer.queue_urls)
    for thread in threads:
        thread.join()


if __name__ == "__main__":  # pragma: no cover
    main()
