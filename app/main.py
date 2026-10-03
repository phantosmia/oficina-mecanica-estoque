from fastapi import FastAPI

from app.shared.logging_config import RequestIDMiddleware, configure_logging
from app.shared.settings import settings
from app.stock.controller import router as stock_router
from app.system.controller import router as system_router

configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    description=(
        "Microsserviço de Estoque da oficina mecânica: saldo por peça e reservas das ordens de serviço. "
        "Reservas, baixas e compensações chegam pela saga (SQS); a API REST é administrativa e exige o "
        "JWT de admin emitido pelo OS Service."
    ),
    version="1.0.0",
)

app.add_middleware(RequestIDMiddleware)

app.include_router(system_router)
app.include_router(stock_router)
