import logging
import time
from pathlib import Path as FilePath
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.core.errors import PipedriveError, PipedriveFileNotFoundError
from app.models.proposal import (
    CreateProposalPdfRequest,
    GetProposalResponse,
    PipedriveCheckResponse,
    PipedriveCreateResponse,
    PipedriveAttachmentResponse,
    PipedriveDeal,
)
from app.services.proposal import ProposalService
from app.services.proposal_pdf import ProposalPdfService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


def _pdf_response(content: bytes, filename: str, extra_headers: dict[str, str] | None = None) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "proposta.pdf"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    headers = {"Content-Disposition": disposition}
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        content=content,
        media_type="application/pdf",
        headers=headers,
    )


def _proposal_pipedrive_data(request: Request, proposal, requested_id: int) -> tuple[str, str, object, str] | None:
    header = proposal.Cabecalho
    if header is None:
        return None
    proposal_id = str(header.IdMemoria or requested_id).strip() or str(requested_id)
    domain = request.app.state.pipedrive_client.domain_for_company(header.CodEmpresa, header.Empresa)
    if not domain:
        return None
    filename = ProposalPdfService.filename_for(proposal)
    return proposal_id, FilePath(filename).stem, ProposalPdfService.total_for(proposal), domain


def _deal_url(domain: str, deal_id: object) -> str:
    return f"https://{domain}.pipedrive.com/deal/{deal_id}"


def _pipedrive_download_error(request: Request, status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "sucesso": False,
            "mensagem": message,
            "correlation_id": getattr(request.state, "correlation_id", None),
        },
    )


def _matching_deal(deals: list[dict], proposal_id: str, domain: str) -> PipedriveDeal | None:
    matches = _matching_deals(deals, proposal_id, domain)
    return matches[0] if matches else None


def _matching_deals(deals: list[dict], proposal_id: str, domain: str) -> list[PipedriveDeal]:
    matches: list[PipedriveDeal] = []
    for deal in deals:
        title = deal.get("title")
        has_proposal_prefix = (
            isinstance(title, str)
            and title.startswith(proposal_id)
            and (len(title) == len(proposal_id) or not title[len(proposal_id)].isdigit())
        )
        if has_proposal_prefix:
            deal_id = str(deal["id"])
            matches.append(PipedriveDeal(id=deal_id, title=title, url=_deal_url(domain, deal_id)))
    return matches


@router.get("/{id_memoria}/pipedrive/download", response_class=Response)
async def download_existing_pipedrive_pdf(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memoria de calculo no Sankhya"),
) -> Response:
    """Download the latest PDF generated for a proposal and stored in Pipedrive."""
    client = request.app.state.pipedrive_client
    if not client.enabled:
        return _pipedrive_download_error(request, 503, "Integracao com Pipedrive nao configurada.")

    proposal_id = str(id_memoria)
    try:
        for domain in client.configured_domains():
            deals = _matching_deals(await client.search_deals(domain, proposal_id), proposal_id, domain)
            for deal in deals:
                try:
                    file = client.proposal_pdf(await client.list_deal_files(domain, deal.id), proposal_id)
                except PipedriveFileNotFoundError:
                    continue
                content = await client.download_file(domain, str(file["id"]))
                filename = str(file.get("name") or file.get("file_name") or f"proposta-{proposal_id}.pdf")
                return _pdf_response(content, filename, {"X-Pipedrive-Deal-Url": deal.url})
    except PipedriveError:
        logger.warning("pipedrive_download_failed", extra={"proposal_id": proposal_id}, exc_info=True)
        return _pipedrive_download_error(request, 502, "Nao foi possivel baixar o PDF do Pipedrive.")

    return _pipedrive_download_error(request, 404, "Nenhum PDF desta proposta foi encontrado no Pipedrive.")


@router.post(
    "/{id_memoria}/pipedrive/deals/{deal_id}/pdf",
    response_model=PipedriveAttachmentResponse,
)
async def attach_pdf_to_existing_pipedrive_deal(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memoria de calculo no Sankhya"),
    deal_id: int = Path(gt=0, description="ID do negocio existente no Pipedrive"),
    responsavel: str = Query(default=""),
    email_cliente: str = Query(default=""),
) -> PipedriveAttachmentResponse:
    """Attach a proposal PDF to an existing matching deal, without creating one."""
    client = request.app.state.pipedrive_client
    if not client.enabled:
        return PipedriveAttachmentResponse(message="Integracao com Pipedrive nao configurada.")

    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    data = _proposal_pipedrive_data(request, proposal, id_memoria)
    if data is None:
        return PipedriveAttachmentResponse(message="A empresa da proposta nao possui um dominio Pipedrive configurado.")
    proposal_id, _, _, domain = data
    try:
        matches = _matching_deals(await client.search_deals(domain, proposal_id), proposal_id, domain)
        deal = next((candidate for candidate in matches if candidate.id == str(deal_id)), None)
        if deal is None:
            return PipedriveAttachmentResponse(
                message="O negocio informado nao corresponde a esta proposta no Pipedrive.",
            )
        generated = await run_in_threadpool(
            request.app.state.pdf_service.generate,
            proposal,
            responsavel,
            email_cliente,
        )
        await client.upload_pdf(domain, deal.id, generated.filename, generated.content)
    except PipedriveError:
        logger.warning("pipedrive_upload_failed", extra={"proposal_id": proposal_id, "deal_id": deal_id}, exc_info=True)
        return PipedriveAttachmentResponse(
            message="Nao foi possivel anexar o PDF no Pipedrive.",
        )
    return PipedriveAttachmentResponse(attached=True, deal=deal)


@router.post(
    "/{id_memoria}/pipedrive/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def create_pipedrive_deal_and_pdf(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memoria de calculo no Sankhya"),
    responsavel: str = Query(default=""),
    email_cliente: str = Query(default=""),
) -> Response:
    """Generate the PDF first, then create and attach it to a new Pipedrive deal."""
    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    generated = await run_in_threadpool(
        request.app.state.pdf_service.generate,
        proposal,
        responsavel,
        email_cliente,
    )
    client = request.app.state.pipedrive_client
    data = _proposal_pipedrive_data(request, proposal, id_memoria)
    if not client.enabled or data is None:
        return _pdf_response(
            generated.content,
            generated.filename,
            {"X-Pipedrive-Message": "Pipedrive nao esta configurado para esta proposta; PDF gerado normalmente."},
        )

    proposal_id, title, value, domain = data
    try:
        # Every write is preceded by a server-side search, even after the UI check.
        await client.search_deals(domain, proposal_id)
        created = await client.create_deal(domain, title, value)
    except PipedriveError:
        logger.warning("pipedrive_create_failed", extra={"proposal_id": proposal_id}, exc_info=True)
        return _pdf_response(
            generated.content,
            generated.filename,
            {"X-Pipedrive-Message": "Nao foi possivel criar o negocio no Pipedrive; PDF gerado normalmente."},
        )

    deal_id = str(created["id"])
    headers = {"X-Pipedrive-Deal-Url": _deal_url(domain, deal_id)}
    try:
        await client.upload_pdf(domain, deal_id, generated.filename, generated.content)
    except PipedriveError:
        logger.warning("pipedrive_upload_failed", extra={"proposal_id": proposal_id, "deal_id": deal_id}, exc_info=True)
        headers["X-Pipedrive-Message"] = "Negocio criado no Pipedrive, mas nao foi possivel anexar o PDF."
    return _pdf_response(generated.content, generated.filename, headers)


@router.get("/{id_memoria}/pipedrive/check", response_model=PipedriveCheckResponse)
async def check_pipedrive_deal(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memoria de calculo no Sankhya"),
) -> PipedriveCheckResponse:
    client = request.app.state.pipedrive_client
    if not client.enabled:
        return PipedriveCheckResponse(status="disabled")

    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    data = _proposal_pipedrive_data(request, proposal, id_memoria)
    if data is None:
        return PipedriveCheckResponse(
            status="unavailable",
            message="A empresa da proposta nao possui um dominio Pipedrive configurado. O PDF sera gerado normalmente.",
        )
    proposal_id, _, _, domain = data
    try:
        deal = _matching_deal(await client.search_deals(domain, proposal_id), proposal_id, domain)
    except PipedriveError:
        logger.warning("pipedrive_check_failed", extra={"proposal_id": proposal_id}, exc_info=True)
        return PipedriveCheckResponse(
            status="unavailable",
            message="Nao foi possivel consultar o Pipedrive. Nenhum negocio sera criado e o PDF sera gerado normalmente.",
        )
    return PipedriveCheckResponse(status="existing" if deal else "not_found", existing_deal=deal)


@router.post("/{id_memoria}/pipedrive/deal", response_model=PipedriveCreateResponse)
async def create_pipedrive_deal(
    request: Request,
    id_memoria: int = Path(gt=0, description="ID da memoria de calculo no Sankhya"),
) -> PipedriveCreateResponse:
    client = request.app.state.pipedrive_client
    if not client.enabled:
        return PipedriveCreateResponse(message="Integracao com Pipedrive nao configurada.")

    proposal = await ProposalService(request.app.state.sankhya_client).get_proposal(id_memoria)
    data = _proposal_pipedrive_data(request, proposal, id_memoria)
    if data is None:
        return PipedriveCreateResponse(message="A empresa da proposta nao possui um dominio Pipedrive configurado.")
    proposal_id, title, value, domain = data
    try:
        # A search is intentionally repeated immediately before every write.
        # The UI may still allow a duplicate after explicit user confirmation.
        await client.search_deals(domain, proposal_id)
        created = await client.create_deal(domain, title, value)
    except PipedriveError:
        logger.warning("pipedrive_create_failed", extra={"proposal_id": proposal_id}, exc_info=True)
        return PipedriveCreateResponse(
            message="Nao foi possivel criar o negocio no Pipedrive. O PDF sera gerado normalmente.",
        )
    deal_id = str(created["id"])
    return PipedriveCreateResponse(
        created=True,
        deal=PipedriveDeal(id=deal_id, title=title, url=_deal_url(domain, deal_id)),
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
