from dataclasses import dataclass
from urllib.parse import quote
import os


def _build_default_database_url() -> str:
    """URL do PostgreSQL a partir de POSTGRES_* (mesma regra do OS Service:
    usuário e senha passam por `quote()` porque a senha gerada pelo RDS pode
    conter caracteres especiais). `DATABASE_URL`, se definida, tem precedência."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = quote(os.getenv("POSTGRES_USER", "estoque"), safe="")
    password = quote(os.getenv("POSTGRES_PASSWORD", "estoque"), safe="")
    db = os.getenv("POSTGRES_DB", "oficina_estoque")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


@dataclass(frozen=True)
class Settings:
    app_name: str
    log_level: str
    database_url: str
    # JWT de admin: emitido pelo OS Service; este serviço só valida.
    jwt_secret_key: str
    jwt_algorithm: str
    admin_username: str
    # AWS (localmente, AWS_ENDPOINT_URL aponta pro LocalStack)
    aws_region: str
    events_topic_arn: str
    commands_queue_url: str
    catalog_events_queue_url: str
    worker_wait_seconds: int
    outbox_poll_interval_seconds: float


settings = Settings(
    app_name="Oficina Mecânica — Estoque",
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    database_url=os.getenv("DATABASE_URL", _build_default_database_url()),
    jwt_secret_key=os.getenv("JWT_SECRET_KEY", "change-me-in-production"),
    jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    admin_username=os.getenv("ADMIN_USERNAME", "admin"),
    aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
    events_topic_arn=os.getenv("ESTOQUE_EVENTS_TOPIC_ARN", ""),
    commands_queue_url=os.getenv("ESTOQUE_COMMANDS_QUEUE_URL", ""),
    catalog_events_queue_url=os.getenv("ESTOQUE_CATALOG_EVENTS_QUEUE_URL", ""),
    worker_wait_seconds=int(os.getenv("WORKER_WAIT_SECONDS", "10")),
    outbox_poll_interval_seconds=float(os.getenv("OUTBOX_POLL_INTERVAL_SECONDS", "2")),
)
