import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.api.routes.proposals import router as proposals_router
from app.clients.sankhya import SankhyaClient
from app.core.config import get_settings
from app.core.errors import PdfGenerationError, SankhyaError, SankhyaHTTPError, SankhyaUnavailableError
from app.core.logging import configure_logging
from app.services.proposal_pdf import ProposalPdfService


logger = logging.getLogger(__name__)
_WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    async with SankhyaClient(settings) as client:
        app.state.sankhya_client = client
        app.state.pdf_service = ProposalPdfService(
            settings.templates_dir,
            converter=settings.pdf_converter,
            libreoffice_executable=settings.libreoffice_executable,
            conversion_timeout=settings.pdf_conversion_timeout,
        )
        yield


app = FastAPI(
    title="Sankhya GetProposal API",
    version="0.1.9",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")
app.include_router(proposals_router)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def web_interface() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_WEB_DIR / "static" / "favicon.ico", media_type="image/vnd.microsoft.icon")


@app.exception_handler(SankhyaUnavailableError)
async def unavailable_handler(request: Request, exc: SankhyaUnavailableError) -> JSONResponse:
    return _error_response(request, 504, "Timeout ou indisponibilidade da API Sankhya", exc)


@app.exception_handler(SankhyaHTTPError)
async def http_error_handler(request: Request, exc: SankhyaHTTPError) -> JSONResponse:
    status_code = 502
    if exc.status_code in (401, 403):
        status_code = 502
    elif exc.status_code == 404:
        status_code = 404
    elif exc.status_code == 429:
        status_code = 503
    return _error_response(request, status_code, "Falha ao consultar a API Sankhya", exc)


@app.exception_handler(SankhyaError)
async def sankhya_error_handler(request: Request, exc: SankhyaError) -> JSONResponse:
    return _error_response(request, 502, "Resposta inválida da API Sankhya", exc)


@app.exception_handler(ValidationError)
async def settings_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return _error_response(request, 500, "Configuração da aplicação inválida", exc)


@app.exception_handler(PdfGenerationError)
async def pdf_error_handler(request: Request, exc: PdfGenerationError) -> JSONResponse:
    return _error_response(request, 422, str(exc), exc)


def _error_response(request: Request, status_code: int, message: str, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.error(
        "request_failed",
        extra={
            "correlation_id": correlation_id,
            "error_type": type(exc).__name__,
            "status_code": status_code,
        },
    )
    return JSONResponse(
        status_code=status_code,
        content={"sucesso": False, "mensagem": message, "correlation_id": correlation_id},
    )
