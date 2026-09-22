import base64
import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from app.core.errors import PdfGenerationError
from app.models.proposal import Proposal, ProposalItem
from app.services.seller_directory import SellerDirectory
from app.services.libreoffice_pdf import LibreOfficePdfConverter
from app.services.word_pdf import WordPdfConverter, WordRenderJob


@dataclass(frozen=True)
class GeneratedPdf:
    content: bytes
    filename: str


_COMPANY_DATA = {
    "1": (
        "JT INSTRUMENTAÇÃO E PROCESSOS INDUSTRIAIS LTDA",
        "14.400.275/0001-27",
        "407283943111",
    ),
    "2": (
        "JT INSTRUMENTAÇÃO E PROCESSOS INDUSTRIAIS LTDA",
        "14.400.275/0002-08",
        "260717398",
    ),
    "3": (
        "4X Process Technologies LTDA",
        "54.837.804/0001-79",
        "262895633",
    ),
}


class ProposalPdfService:
    def __init__(
        self,
        templates_dir: Path,
        converter: str = "word",
        libreoffice_executable: Path | None = None,
        conversion_timeout: int = 120,
    ):
        self._templates_dir = templates_dir.resolve()
        if converter == "libreoffice":
            self._converter = LibreOfficePdfConverter(
                libreoffice_executable,
                conversion_timeout,
            )
        elif converter == "word":
            self._converter = WordPdfConverter()
        else:
            raise PdfGenerationError(f"Conversor PDF desconhecido: {converter}")
        self._sellers = SellerDirectory(self._templates_dir / "Dados.xlsx")

    def generate(self, proposal: Proposal, responsible: str, client_email: str) -> GeneratedPdf:
        if proposal.Cabecalho is None:
            raise PdfGenerationError("A proposta não possui cabeçalho")

        is_service = self._text(proposal.Cabecalho.CodTipoOperacao) == "997"
        header_template = (
            "Cabecalho_4X.docx"
            if self._text(proposal.Cabecalho.CodEmpresa) == "3"
            else "Cabecalho.docx"
        )
        seller = self._sellers.find(proposal.Vendedor)
        with tempfile.TemporaryDirectory(prefix="proposal-") as temp_name:
            temp = Path(temp_name)
            header_docx = temp / "01_Cabecalho.docx"
            items_docx = temp / "55_Itens.docx"
            terms_docx = temp / "99_Condicoes.docx"
            header_pdf = temp / "01_Cabecalho.pdf"
            items_pdf = temp / "55_Itens.pdf"
            terms_pdf = temp / "99_Condicoes.pdf"

            self._converter.render_many(
                [
                    WordRenderJob(
                        template=self._templates_dir / header_template,
                        working_document=header_docx,
                        output_pdf=header_pdf,
                        fields=self._header_fields(
                            proposal, responsible, client_email, seller
                        ),
                        field_font_sizes={"REV": 10},
                    ),
                    WordRenderJob(
                        template=self._templates_dir / ("Itens_servico.docx" if is_service else "Itens.docx"),
                        working_document=items_docx,
                        output_pdf=items_pdf,
                        fields={
                            "TotalImpostos_Proposta": f"R$ {self._format_number(proposal.Cabecalho.ValorNota, 2, True)}",
                        },
                        repeating_section="Itens",
                        field_font_sizes={"TotalImpostos_Proposta": 10},
                        repeating_rows=[
                            self._item_fields(
                                item,
                                is_service=is_service,
                            )
                            for item in proposal.Itens
                        ],
                    ),
                    WordRenderJob(
                        template=self._templates_dir / "Condicoes.docx",
                        working_document=terms_docx,
                        output_pdf=terms_pdf,
                        fields=self._terms_fields(proposal),
                        field_font_size_points=12,
                    ),
                ]
            )

            parts = [header_pdf.read_bytes(), items_pdf.read_bytes()]
            parts.extend(
                self._decode_product_pdf(item.PdfBase64, item.CodProd)
                for item in proposal.Itens
                if item.PdfBase64
            )
            parts.append(terms_pdf.read_bytes())
            return GeneratedPdf(
                content=self._merge(parts),
                filename=self._filename(proposal),
            )

    @staticmethod
    def _header_fields(
        proposal: Proposal,
        responsible: str,
        client_email: str,
        seller: dict[str, str],
    ) -> dict[str, str]:
        header = proposal.Cabecalho
        assert header is not None
        return {
            "VendedorCelular": seller["Telefone"],
            "Vendedor": proposal.Vendedor,
            "Responsavel": responsible,
            "EmailCliente": client_email,
            "Cliente": ProposalPdfService._text(header.Cliente),
            "NumeroProposta": ProposalPdfService._text(header.IdMemoria),
            "REV": ProposalPdfService._revision(header.Revisao),
            "VendedorEmail": seller["Email"],
            "DataProposta": ProposalPdfService._text(header.DataProposta),
        }

    @staticmethod
    def _item_fields(item: ProposalItem, *, is_service: bool = False) -> dict[str, str]:
        description = ProposalPdfService._text(item.DescricaoCompleta).replace(" - ", "\n- ")
        fields = {
            "Item": ProposalPdfService._text(item.Sequencia),
            "Quantidade": f"{ProposalPdfService._format_number(item.Quantidade, 2, False)} UN",
            "Descricao": f"{description}\n\n",
            "ValorUnitario": f"R$ {ProposalPdfService._format_number(item.ValorUnitLiquido, 2, True)}",
            "ValorTotal": f"R$ {ProposalPdfService._format_number(item.ValorTotalLiquido, 2, True)}",
            "TotalImpostos": f"R$ {ProposalPdfService._format_number(item.ValorTotalIPI, 2, True)}",
            "Codigo": "" if is_service else ProposalPdfService._text(item.CodigoTemplate),
            "Entrega": ProposalPdfService._text(item.PrevisaoEntrega),
            "NCM": ProposalPdfService._text(item.NCM),
            "IPI": f"{ProposalPdfService._format_number(item.AliqIPI, 2, False)}%",
            "ICMS": f"{ProposalPdfService._format_number(item.AliqICMS, 2, False)}%",
        }
        if is_service:
            for name in ("Codigo", "NCM", "IPI", "ICMS"):
                fields.pop(name)
        return fields

    @staticmethod
    def _terms_fields(proposal: Proposal) -> dict[str, str]:
        header = proposal.Cabecalho
        assert header is not None
        company = _COMPANY_DATA.get(ProposalPdfService._text(header.CodEmpresa), ("", "", ""))
        freight = ""
        if ProposalPdfService._text(header.CifFob) == "F":
            freight_company = "4X" if ProposalPdfService._text(header.CodEmpresa) == "3" else "JT"
            freight = f"Condição: FOB {freight_company} – Jundiaí/SP."
        elif ProposalPdfService._text(header.CifFob) == "C":
            freight = "Condição: CIF."
        return {
            "CNPJ": company[1],
            "RazaoSocial": company[0],
            "InscricaoEstadual": company[2],
            "ValorTaxa": ProposalPdfService._text(header.ValorTaxa),
            "Frete": freight,
            "CondicaoPagamento": ProposalPdfService._text(header.CondicaoPagamento),
        }

    @staticmethod
    def _format_number(value: Any, decimal_places: int, grouping: bool) -> str:
        number = ProposalPdfService._decimal(value)
        quantizer = Decimal(1).scaleb(-decimal_places)
        number = number.quantize(quantizer, rounding=ROUND_HALF_UP)
        formatted = f"{number:,.{decimal_places}f}" if grouping else f"{number:.{decimal_places}f}"
        if not grouping:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted.replace(",", "_").replace(".", ",").replace("_", ".")

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        raw = ProposalPdfService._text(value).strip()
        if not raw:
            return Decimal("0")
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise PdfGenerationError(f"Valor numérico inválido: {value}") from exc

    @staticmethod
    def _revision(value: Any) -> str:
        raw = ProposalPdfService._text(value).strip()
        if not raw:
            return "00"
        try:
            return f"{int(Decimal(raw)):02d}"
        except (InvalidOperation, ValueError) as exc:
            raise PdfGenerationError(f"Revisão inválida: {value}") from exc

    @staticmethod
    def _decode_product_pdf(value: str, product_code: Any) -> bytes:
        encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise PdfGenerationError(f"PDF base64 inválido no produto {product_code}") from exc
        if not content.lstrip().startswith(b"%PDF-"):
            raise PdfGenerationError(f"Anexo do produto {product_code} não é PDF")
        return content

    @staticmethod
    def _merge(parts: list[bytes]) -> bytes:
        writer = PdfWriter()
        try:
            for content in parts:
                reader = PdfReader(BytesIO(content))
                for page in reader.pages:
                    writer.add_page(page)
            output = BytesIO()
            writer.write(output)
            return output.getvalue()
        except Exception as exc:
            raise PdfGenerationError(f"Falha ao combinar PDFs: {exc}") from exc

    @staticmethod
    def _filename(proposal: Proposal) -> str:
        header = proposal.Cabecalho
        assert header is not None
        first_description = (
            ProposalPdfService._text(proposal.Itens[0].DescricaoCompleta) if proposal.Itens else ""
        )
        product = first_description.split(" - ", 1)[0].strip()
        raw = (
            f"{ProposalPdfService._text(header.IdMemoria)} PCV - "
            f"{ProposalPdfService._text(header.Cliente)} - {product} - "
            f"REV {ProposalPdfService._revision(header.Revisao)}.pdf"
        )
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
        return sanitized or "proposta.pdf"

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value)
