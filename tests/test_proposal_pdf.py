import base64
import zipfile
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from lxml import etree

from app.models.proposal import Proposal, ProposalHeader, ProposalItem
from app.services.proposal_pdf import ProposalPdfService
from app.services.docx_templates import DocxContentControlRenderer


def one_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeConverter:
    def render_many(self, jobs) -> None:
        for job in jobs:
            assert job.template.is_file()
            job.working_document.write_bytes(job.template.read_bytes())
            job.output_pdf.write_bytes(one_page_pdf())


def proposal_with_product_pdf() -> Proposal:
    return Proposal(
        Cabecalho=ProposalHeader(
            IdMemoria="123",
            DataProposta="10/09/2026",
            Cliente="CLIENTE TESTE",
            Revisao="2",
            CodEmpresa="1",
            ValorTaxa="5.25",
            CifFob="F",
            CondicaoPagamento="28 dias",
        ),
        Vendedor="VENDEDOR INEXISTENTE PARA TESTE",
        Itens=[
            ProposalItem(
                Sequencia="1",
                CodProd="10",
                Quantidade="2.5",
                DescricaoCompleta="PRODUTO - CARACTERÍSTICA",
                ValorUnitLiquido="1234.5",
                ValorTotalLiquido="2469",
                ValorTotalIPI="2592.45",
                CodigoTemplate="ABC",
                PrevisaoEntrega="30 dias",
                NCM="1234.56.78",
                AliqIPI="5",
                AliqICMS="18",
                PdfBase64=base64.b64encode(one_page_pdf()).decode("ascii"),
            )
        ],
    )


def test_full_local_pipeline_preserves_merge_order_and_filename() -> None:
    service = ProposalPdfService(Path("Templates"))
    service._converter = FakeConverter()  # type: ignore[assignment]

    generated = service.generate(proposal_with_product_pdf(), "Responsável", "cliente@example.com")

    assert generated.filename == "123 PCV - CLIENTE TESTE - PRODUTO - REV 02.pdf"
    assert len(PdfReader(BytesIO(generated.content)).pages) == 4


def test_power_automate_number_formatting_rules() -> None:
    assert ProposalPdfService._format_number("1234.5", 2, True) == "1.234,50"
    assert ProposalPdfService._format_number("2.50", 2, False) == "2,5"
    assert ProposalPdfService._format_number("18", 2, False) == "18"


def test_company_and_freight_rules() -> None:
    fields = ProposalPdfService._terms_fields(proposal_with_product_pdf())

    assert fields["CNPJ"] == "14.400.275/0001-27"
    assert fields["RazaoSocial"] == "JT INSTRUMENTAÇÃO E PROCESSOS INDUSTRIAIS LTDA"
    assert fields["Frete"] == "Condição: FOB – JT – Jundiaí/SP."


def test_ooxml_renderer_duplicates_items_without_word(tmp_path: Path) -> None:
    destination = tmp_path / "Itens.docx"
    rows = [
        ProposalPdfService._item_fields(proposal_with_product_pdf().Itens[0]),
        ProposalPdfService._item_fields(
            proposal_with_product_pdf().Itens[0].model_copy(update={"Sequencia": "2"})
        ),
    ]
    DocxContentControlRenderer().render_repeating(
        Path("Templates/Itens.docx"), destination, "Itens", rows
    )

    with zipfile.ZipFile(destination) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    item_values = root.xpath(
        ".//w:sdt[w:sdtPr/w:tag[@w:val='Item']]/w:sdtContent//w:t/text()",
        namespaces=namespace,
    )
    assert item_values == ["1", "2"]
