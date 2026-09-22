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
    assert fields["Frete"] == "Condição: FOB JT – Jundiaí/SP."


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
    assert not root.xpath(".//w:sdt", namespaces=namespace)
    item_runs = [
        run
        for run in root.xpath(".//w:r", namespaces=namespace)
        if "".join(run.xpath("./w:t/text()", namespaces=namespace)) in {"1", "2"}
    ]
    item_values = [
        "".join(run.xpath("./w:t/text()", namespaces=namespace)) for run in item_runs
    ]
    assert item_values == ["1", "2"]

    assert len(item_runs) == 2
    for run in item_runs:
        fonts = run.find("w:rPr/w:rFonts", namespaces=namespace)
        size = run.find("w:rPr/w:sz", namespaces=namespace)
        complex_size = run.find("w:rPr/w:szCs", namespaces=namespace)
        assert fonts is not None
        assert size is not None
        assert complex_size is not None
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            assert fonts.get(f"{{{namespace['w']}}}{attribute}") == "Liberation Sans"
        assert size.get(f"{{{namespace['w']}}}val") == "16"
        assert complex_size.get(f"{{{namespace['w']}}}val") == "16"


def test_ooxml_renderer_uses_paragraphs_for_multiline_description(tmp_path: Path) -> None:
    destination = tmp_path / "Itens.docx"
    DocxContentControlRenderer().render_repeating(
        Path("Templates/Itens.docx"),
        destination,
        "Itens",
        [{"Descricao": "AAA\n- BBB\n- CCC"}],
    )

    with zipfile.ZipFile(destination) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    assert not root.xpath(".//w:sdt", namespaces=namespace)
    expected_lines = {"AAA", "- BBB", "- CCC"}
    paragraphs = [
        paragraph
        for paragraph in root.xpath(".//w:p", namespaces=namespace)
        if "".join(paragraph.xpath(".//w:t/text()", namespaces=namespace))
        in expected_lines
    ]
    assert ["".join(p.xpath(".//w:t/text()", namespaces=namespace)) for p in paragraphs] == [
        "AAA",
        "- BBB",
        "- CCC",
    ]
    assert not any(p.xpath(".//w:br", namespaces=namespace) for p in paragraphs)


def test_ooxml_renderer_forces_header_field_font_and_size(tmp_path: Path) -> None:
    destination = tmp_path / "Cabecalho.docx"
    DocxContentControlRenderer().render(
        Path("Templates/Cabecalho.docx"),
        destination,
        {"Vendedor": "VENDEDOR TESTE"},
    )

    with zipfile.ZipFile(destination) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    assert not root.xpath(".//w:sdt", namespaces=namespace)
    runs = [
        run
        for run in root.xpath(".//w:r", namespaces=namespace)
        if "".join(run.xpath("./w:t/text()", namespaces=namespace)) == "VENDEDOR TESTE"
    ]
    assert len(runs) == 1
    run = runs[0]
    paragraph = run.getparent()
    properties = [run.find("w:rPr", namespaces=namespace)]
    if paragraph.tag == f"{{{namespace['w']}}}p":
        properties.append(paragraph.find("w:pPr/w:rPr", namespaces=namespace))
    properties = [properties_node for properties_node in properties if properties_node is not None]
    assert properties
    for run_properties in properties:
        fonts = run_properties.find("w:rFonts", namespaces=namespace)
        size = run_properties.find("w:sz", namespaces=namespace)
        complex_size = run_properties.find("w:szCs", namespaces=namespace)
        assert fonts is not None
        assert size is not None
        assert complex_size is not None
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            assert fonts.get(f"{{{namespace['w']}}}{attribute}") == "Liberation Sans"
        assert size.get(f"{{{namespace['w']}}}val") == "16"
        assert complex_size.get(f"{{{namespace['w']}}}val") == "16"


def test_ooxml_renderer_uses_12_points_for_terms_fields(tmp_path: Path) -> None:
    destination = tmp_path / "Condicoes.docx"
    DocxContentControlRenderer().render(
        Path("Templates/Condicoes.docx"),
        destination,
        {"CondicaoPagamento": "28 DIAS"},
        font_size_points=12,
    )

    with zipfile.ZipFile(destination) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    runs = [
        run
        for run in root.xpath(".//w:r", namespaces=namespace)
        if "".join(run.xpath("./w:t/text()", namespaces=namespace)) == "28 DIAS"
    ]
    assert len(runs) == 1
    size = runs[0].find("w:rPr/w:sz", namespaces=namespace)
    complex_size = runs[0].find("w:rPr/w:szCs", namespaces=namespace)
    assert size is not None
    assert complex_size is not None
    assert size.get(f"{{{namespace['w']}}}val") == "24"
    assert complex_size.get(f"{{{namespace['w']}}}val") == "24"
