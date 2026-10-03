#!/bin/bash
set -e

# Mesma imagem para os quatro papéis do serviço:
#   docker-entrypoint.sh            -> API (uvicorn)
#   docker-entrypoint.sh worker     -> consumidor das filas SQS (comandos da saga, eventos do Catálogo)
#   docker-entrypoint.sh relay      -> relay da outbox (publica eventos no SNS)
#   docker-entrypoint.sh migrate    -> aplica as migrations e sai (Job no Kubernetes)
ROLE="${1:-api}"

if [ "$ROLE" = "migrate" ]; then
    echo "Aplicando migrations..."
    alembic upgrade head
    if [ "${SEED_ON_MIGRATE:-false}" = "true" ]; then
        echo "Carregando saldo inicial de exemplo..."
        python -m scripts.seed
    fi
    exit 0
fi

# Só no docker-compose (LocalStack): na AWS, filas e tópico vêm do Terraform.
if [ "${BOOTSTRAP_LOCAL_RESOURCES:-false}" = "true" ]; then
    echo "Criando filas e tópico locais..."
    python -m scripts.bootstrap_local
fi

# Agente APM do New Relic (ADR-0007) só quando a license key estiver definida.
RUNNER=()
if [ -n "${NEW_RELIC_LICENSE_KEY:-}" ]; then
    RUNNER=(newrelic-admin run-program)
fi

case "$ROLE" in
    worker)
        echo "Iniciando worker das filas..."
        exec "${RUNNER[@]}" python -m app.worker
        ;;
    relay)
        echo "Iniciando relay da outbox..."
        exec "${RUNNER[@]}" python -m app.outbox_relay
        ;;
    *)
        echo "Iniciando API do Estoque..."
        exec "${RUNNER[@]}" uvicorn app.main:app --host 0.0.0.0 --port 8000
        ;;
esac
