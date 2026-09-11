import base64
from typing import Any, Protocol

from app.core.errors import SankhyaResponseError
from app.models.proposal import Proposal, ProposalHeader, ProposalItem


ITEM_FIELDS = [
    "DTPREVENT", "ID", "SEQ", "CODPROD", "Produto.DESCRPROD", "NCM", "QTD",
    "VLRLISTA", "PERCDESCDIST", "DESCCLIENTE", "VLRDESC", "VLRLISTADESC",
    "VLRUNIT", "VLRFATORIMP", "VLRPISCOFINS", "PERCII", "VLRII", "VLRFOB",
    "PERCMARGEM", "VLRUNITNET", "VLRMARGEM", "VLRIRPCSLL", "VLRTOTUNITNET",
    "PERCMARGEMMAX", "VLRFRETE", "PERCMARGEMMIN", "VLRPISCONFINSVENDA",
    "VLRUNITPISCOFINSVEN", "ALIQICMS", "VLRICMS", "VLRTOTNETICMS",
    "VLRUNITNETICMS", "ALIQIPI", "VLRIPI", "VLRNOTA", "VLRTOTNETIPI",
    "AD_CODIGO", "AD_DESCRCOMPLETA",
]

HEADER_FIELDS = [
    "ID", "DTNEG", "CODPARC", "Parceiro.NOMEPARC", "CODTIPOPER",
    "TipoOperacao.DESCROPER", "CODTIPVENDA", "TipoNegociacao.DESCRTIPVENDA",
    "CODMOEDA", "Moeda.NOMEMOEDA", "DTPTAX", "CODEMP", "Empresa.NOMEFANTASIA",
    "VLRPTAX", "CODCTR", "MemoriaCalculoCtr.DESCRICAO", "NUNOTA", "CODCLA",
    "MemoriaCalculoClaCli.DESCRICAO", "STATUS", "CIF_FOB", "VLRFRETE",
    "DHAPROVACAO", "CODUSUAPROV", "CODNAT", "Natureza.DESCRNAT", "CODCENCUS",
    "CentroResultado.DESCRCENCUS", "IDANTERIOR", "REVISAO", "VLRNOTA", "OBSERVACAO",
]


class ProposalSankhyaClient(Protocol):
    async def request_service(self, service_name: str, body: dict[str, Any], *, query: str = "") -> dict[str, Any]: ...
    async def get_product(self, product_code: Any) -> dict[str, Any]: ...
    async def load_product_attachments(self, product_code: Any) -> dict[str, Any]: ...
    async def view_attachment(self, attachment: dict[str, Any]) -> dict[str, Any]: ...
    async def download_attachment(self, attachment_key: str) -> bytes: ...


class ProposalService:
    def __init__(self, client: ProposalSankhyaClient):
        self._client = client

    async def get_proposal(self, proposal_id: int) -> Proposal:
        header_rows = await self._load_header(proposal_id)
        header = self._normalize_header(header_rows[0]) if header_rows else None

        item_rows = await self._load_items(proposal_id)
        items = [self._normalize_item(row) for row in item_rows]
        if header is not None and str(header.CodTipoOperacao).strip() == "997":
            enriched_items = [
                item.model_copy(update={"CodigoTemplate": "", "Homepage": "", "PdfBase64": ""})
                for item in items
            ]
        else:
            enriched_items = await self._enrich_items(items)

        seller_rows = await self._load_sellers(proposal_id)
        seller_name = self._seller_name(seller_rows)

        return Proposal(Cabecalho=header, Vendedor=seller_name, Itens=enriched_items)

    async def _load_items(self, proposal_id: int) -> list[list[Any]]:
        payload = await self._client.request_service(
            "DatasetSP.loadRecords",
            {
                "dataSetID": "01J",
                "entityName": "MemoriaCalculoIte",
                "standAlone": False,
                "fields": ITEM_FIELDS,
                "tryJoinedFields": True,
                "parallelLoader": True,
                "parentEntityName": "MemoriaCalculoCab",
                "criteria": {
                    "expression": " (ID = ?) ",
                    "parameters": [{"type": "N", "value": proposal_id}],
                },
                "ignoreListenerMethods": "",
                "useDefaultRowsLimit": True,
            },
        )
        return self._result_rows(payload, "itens")

    async def _load_header(self, proposal_id: int) -> list[list[Any]]:
        payload = await self._client.request_service(
            "DatasetSP.loadRecord",
            {
                "dataSetID": "00B",
                "entityName": "MemoriaCalculoCab",
                "pks": [{"ID": proposal_id}],
                "fields": HEADER_FIELDS,
                "tryJoinedFields": True,
                "ignoreListenerMethods": "",
            },
        )
        return self._result_rows(payload, "cabeçalho")

    async def _load_sellers(self, proposal_id: int) -> list[list[Any]]:
        payload = await self._client.request_service(
            "DatasetSP.loadRecords",
            {
                "dataSetID": "02V",
                "entityName": "MemoriaCalculoVen",
                "standAlone": False,
                "fields": ["ID", "CODVEND", "Vendedor.APELIDO"],
                "tryJoinedFields": True,
                "parallelLoader": True,
                "parentEntityName": "MemoriaCalculoCab",
                "criteria": {
                    "expression": " (ID = ?) ",
                    "parameters": [{"type": "N", "value": proposal_id}],
                },
                "ignoreListenerMethods": "",
                "useDefaultRowsLimit": True,
            },
        )
        return self._result_rows(payload, "vendedor")

    async def _enrich_items(self, items: list[ProposalItem]) -> list[ProposalItem]:
        processed_homepages: set[str] = set()
        enriched: list[ProposalItem] = []

        for item in items:
            homepage = ""
            pdf_base64 = ""
            product = await self._client.get_product(item.CodProd)
            products = product.get("produtos")
            if isinstance(products, list):
                products = products[0] if products else {}
            if isinstance(products, dict):
                homepage = str(products.get("homepage") or "").strip().lower()

            if homepage and homepage not in processed_homepages:
                attachment = self._first_description_pdf(
                    await self._client.load_product_attachments(item.CodProd)
                )
                if attachment is not None:
                    view = await self._client.view_attachment(attachment)
                    key = (
                        view.get("responseBody", {})
                        .get("chaveAnexo", {})
                        .get("idChaveAnexo")
                    )
                    if not key:
                        raise SankhyaResponseError("Attach.view não retornou idChaveAnexo")
                    pdf = await self._client.download_attachment(str(key))
                    pdf_base64 = base64.b64encode(pdf).decode("ascii")
                    # Equivalência com o flow: somente marca após download bem-sucedido.
                    processed_homepages.add(homepage)

            enriched.append(item.model_copy(update={"Homepage": homepage, "PdfBase64": pdf_base64}))
        return enriched

    @staticmethod
    def _first_description_pdf(payload: dict[str, Any]) -> dict[str, Any] | None:
        attachments: Any = payload.get("responseBody", {}).get("anexos", {}).get("anexo", [])
        if isinstance(attachments, dict):
            attachments = [attachments]
        if not isinstance(attachments, list):
            return None

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            description = str(attachment.get("DESCRICAO") or "").strip().lower()
            filename = str(attachment.get("ARQUIVO") or "").lower()
            has_content = str(attachment.get("TEMCONTEUDO") or "N").upper()
            if description == "descricao" and filename.endswith(".pdf") and has_content == "S":
                return attachment
        return None

    @staticmethod
    def _normalize_item(row: list[Any]) -> ProposalItem:
        ProposalService._require_columns(row, 38, "item")
        return ProposalItem(
            Sequencia=row[2], CodProd=row[3], DescricaoProduto=row[4], NCM=row[5],
            Quantidade=row[6], ValorUnitLiquido=row[19], ValorTotalLiquido=row[22],
            ValorUnitPisCofins=row[27], AliqICMS=row[28], ValorTotalICMS=row[30],
            ValorUnitICMS=row[31], AliqIPI=row[32], ValorUnitIPI=row[34],
            ValorTotalIPI=row[35], CodigoTemplate=row[36], DescricaoCompleta=row[37],
            PrevisaoEntrega=row[0],
        )

    @staticmethod
    def _normalize_header(row: list[Any]) -> ProposalHeader:
        ProposalService._require_columns(row, 32, "cabeçalho")
        names = [
            "IdMemoria", "DataProposta", "CodParceiro", "Cliente", "CodTipoOperacao",
            "TipoOperacao", "CodTipoVenda", "CondicaoPagamento", "CodMoeda", "Moeda",
            "DataTaxa", "CodEmpresa", "Empresa", "ValorTaxa", "CodControle",
            "DescricaoControle", "NuNota", "CodClassificacao", "Classificacao", "Status",
            "CifFob", "ValorFrete", "DataAprovacao", "UsuarioAprovador", "CodNatureza",
            "Natureza", "CodCentroResultado", "CentroResultado", "IdAnterior", "Revisao",
            "ValorNota", "Observacao",
        ]
        return ProposalHeader(**dict(zip(names, row[: len(names)], strict=True)))

    @staticmethod
    def _seller_name(rows: list[list[Any]]) -> str:
        if rows and len(rows[0]) >= 3 and rows[0][2] not in (None, ""):
            return str(rows[0][2])
        return "SEM VENDEDOR CADASTRADO NO SANKHYA"

    @staticmethod
    def _result_rows(payload: dict[str, Any], context: str) -> list[list[Any]]:
        result = payload.get("responseBody", {}).get("result", [])
        if result is None:
            return []
        if not isinstance(result, list):
            raise SankhyaResponseError(f"Resultado de {context} não é uma lista")
        if result and not isinstance(result[0], list):
            raise SankhyaResponseError(f"Linhas de {context} têm formato inesperado")
        return result

    @staticmethod
    def _require_columns(row: list[Any], minimum: int, context: str) -> None:
        if len(row) < minimum:
            raise SankhyaResponseError(
                f"Linha de {context} tem {len(row)} colunas; esperado no mínimo {minimum}"
            )
