import logging
import time
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.models.proposal import CreateProposalPdfRequest, GetProposalResponse
from app.services.proposal import ProposalService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


def _pdf_response(content: bytes, filename: str) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "proposta.pdf"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.post(
    "/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def create_pdf_from_proposal(
    request: Request,
    payload: CreateProposalPdfRequest,
) -> Response:
    generated = await run_in_threadpool(
        request.app.state.pdf_service.generate,
        payload.proposta,
        payload.responsavel,
        payload.email_cliente,
    )
    return _pdf_response(generated.content, generated.filename)


@router.get(
    "/{id_memoria}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_proposal_pdf(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memória de cálculo no Sankhya"),
    responsavel: str = Query(default=""),
    email_cliente: str = Query(default=""),
) -> Response:
    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    generated = await run_in_threadpool(
        request.app.state.pdf_service.generate,
        proposal,
        responsavel,
        email_cliente,
    )
    return _pdf_response(generated.content, generated.filename)


@router.get("/{id_memoria}", response_model=GetProposalResponse)
async def get_proposal(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memória de cálculo no Sankhya"),
) -> GetProposalResponse:
    started = time.monotonic()
    correlation_id = request.state.correlation_id
    logger.info(
        "get_proposal_started",
        extra={"correlation_id": correlation_id, "proposal_id": id_memoria},
    )
    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    logger.info(
        "get_proposal_completed",
        extra={
            "correlation_id": correlation_id,
            "proposal_id": id_memoria,
            "items_count": len(proposal.Itens),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        },
    )
    return GetProposalResponse(proposta=proposal)
