import base64
from typing import Any

import pytest

from app.services.proposal import ProposalService


def item_row(product_code: str, sequence: str = "1") -> list[Any]:
    row: list[Any] = [None] * 38
    row[0] = "10/10/2026"
    row[2] = sequence
    row[3] = product_code
    row[4] = f"Produto {product_code}"
    row[5] = "1234"
    row[6] = "2"
    row[19] = "100.00"
    row[22] = "200.00"
    row[27] = "10.00"
    row[28] = "18"
    row[30] = "36.00"
    row[31] = "118.00"
    row[32] = "5"
    row[34] = "105.00"
    row[35] = "210.00"
    row[36] = "TPL"
    row[37] = "Descrição completa"
    return row


def header_row() -> list[Any]:
    return [str(index) for index in range(32)]


class FakeClient:
    def __init__(self) -> None:
        self.attachment_loads: list[str] = []
        self.downloads: list[str] = []

    async def request_service(self, service_name: str, body: dict[str, Any], *, query: str = "") -> dict[str, Any]:
        entity = body.get("entityName")
        if entity == "MemoriaCalculoIte":
            rows = [item_row("10", "1"), item_row("20", "2")]
        elif entity == "MemoriaCalculoCab":
            rows = [header_row()]
        elif entity == "MemoriaCalculoVen":
            rows = [["123", "7", "VENDEDOR TESTE"]]
        else:
            raise AssertionError(f"Serviço inesperado: {service_name} {body}")
        return {"status": "1", "responseBody": {"result": rows}}

    async def get_product(self, product_code: Any) -> dict[str, Any]:
        return {"produtos": {"homepage": "  MESMA-HOMEPAGE  "}}

    async def load_product_attachments(self, product_code: Any) -> dict[str, Any]:
        self.attachment_loads.append(str(product_code))
        return {
            "responseBody": {
                "anexos": {
                    "anexo": [
                        {
                            "CODATA": product_code,
                            "SEQUENCIA": 1,
                            "TIPO": "R",
                            "DESCRICAO": " Descricao ",
                            "TIPOCONTEUDO": "application/pdf",
                            "ARQUIVO": "catalogo.PDF",
                            "TEMCONTEUDO": "s",
                        }
                    ]
                }
            }
        }

    async def view_attachment(self, attachment: dict[str, Any]) -> dict[str, Any]:
        return {"responseBody": {"chaveAnexo": {"idChaveAnexo": f"key-{attachment['CODATA']}"}}}

    async def download_attachment(self, attachment_key: str) -> bytes:
        self.downloads.append(attachment_key)
        return b"%PDF-1.4 test"


@pytest.mark.asyncio
async def test_get_proposal_maps_data_and_deduplicates_pdf_by_homepage() -> None:
    client = FakeClient()
    proposal = await ProposalService(client).get_proposal(123)

    assert proposal.Cabecalho is not None
    assert proposal.Cabecalho.IdMemoria == "0"
    assert proposal.Vendedor == "VENDEDOR TESTE"
    assert [item.Homepage for item in proposal.Itens] == ["mesma-homepage", "mesma-homepage"]
    assert proposal.Itens[0].PdfBase64 == base64.b64encode(b"%PDF-1.4 test").decode("ascii")
    assert proposal.Itens[1].PdfBase64 == ""
    assert client.attachment_loads == ["10"]
    assert client.downloads == ["key-10"]


@pytest.mark.asyncio
async def test_homepage_is_retried_when_first_product_has_no_pdf() -> None:
    client = FakeClient()
    original = client.load_product_attachments

    async def first_missing(product_code: Any) -> dict[str, Any]:
        if str(product_code) == "10":
            client.attachment_loads.append("10")
            return {"responseBody": {"anexos": {"anexo": []}}}
        return await original(product_code)

    client.load_product_attachments = first_missing  # type: ignore[method-assign]
    proposal = await ProposalService(client).get_proposal(123)

    assert proposal.Itens[0].PdfBase64 == ""
    assert proposal.Itens[1].PdfBase64 != ""
    assert client.attachment_loads == ["10", "20"]


def test_item_mapping_preserves_power_automate_indexes() -> None:
    item = ProposalService._normalize_item(item_row("99"))

    assert item.PrevisaoEntrega == "10/10/2026"
    assert item.CodProd == "99"
    assert item.ValorUnitLiquido == "100.00"
    assert item.ValorUnitIPI == "105.00"  # índice 34 / VLRNOTA no flow original
    assert item.CodigoTemplate == "TPL"

