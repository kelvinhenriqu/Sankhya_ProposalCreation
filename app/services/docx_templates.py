import copy
import random
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from app.core.errors import PdfGenerationError


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
FIELD_FONT_FAMILY = "Liberation Sans"
FIELD_FONT_SIZE_POINTS = 8


class DocxContentControlRenderer:
    """Fills Word content controls without launching Microsoft Word."""

    def render(
        self,
        template: Path,
        destination: Path,
        fields: dict[str, Any],
        *,
        font_size_points: float = FIELD_FONT_SIZE_POINTS,
        field_font_sizes: dict[str, float] | None = None,
    ) -> None:
        root, entries = self._read(template)
        for name, value in fields.items():
            control = self._find_control(root, name)
            if control is None:
                raise PdfGenerationError(f"Controle '{name}' não encontrado em {template.name}")
            self._set_text(control, self._text(value))
            self._set_direct_format(
                control,
                font_family=FIELD_FONT_FAMILY,
                size_half_points=self._half_points((field_font_sizes or {}).get(name, font_size_points)),
            )
        self._unwrap_content_controls(root)
        self._write(destination, root, entries)

    def render_repeating(
        self,
        template: Path,
        destination: Path,
        section_name: str,
        rows: list[dict[str, Any]],
        *,
        fields: dict[str, Any] | None = None,
        font_size_points: float = FIELD_FONT_SIZE_POINTS,
        field_font_sizes: dict[str, float] | None = None,
    ) -> None:
        root, entries = self._read(template)
        size_half_points = self._half_points(font_size_points)
        section = self._find_control(root, section_name)
        if section is None:
            raise PdfGenerationError(f"Seção '{section_name}' não encontrada em {template.name}")
        content = section.find(f"{W}sdtContent")
        if content is None:
            raise PdfGenerationError(f"Seção '{section_name}' sem conteúdo")
        template_item = next(
            (child for child in content if child.tag == f"{W}sdt"),
            None,
        )
        if template_item is None:
            raise PdfGenerationError(f"Item repetitivo ausente em '{section_name}'")

        position = content.index(template_item)
        content.remove(template_item)
        for offset, values in enumerate(rows):
            item = copy.deepcopy(template_item)
            self._refresh_ids(item)
            for name, value in values.items():
                control = self._find_control(item, name)
                if control is None:
                    raise PdfGenerationError(
                        f"Controle repetitivo '{name}' não encontrado em {template.name}"
                    )
                self._set_text(control, self._text(value))
                self._set_direct_format(
                    control,
                    font_family=FIELD_FONT_FAMILY,
                    size_half_points=size_half_points,
                )
            content.insert(position + offset, item)
        for name, value in (fields or {}).items():
            control = self._find_control(root, name)
            if control is None:
                raise PdfGenerationError(f"Controle '{name}' ausente em {template.name}")
            self._set_text(control, self._text(value))
            self._set_direct_format(
                control,
                font_family=FIELD_FONT_FAMILY,
                size_half_points=self._half_points((field_font_sizes or {}).get(name, font_size_points)),
            )
        self._unwrap_content_controls(root)
        self._write(destination, root, entries)

    @staticmethod
    def _read(template: Path) -> tuple[Any, list[tuple[zipfile.ZipInfo, bytes]]]:
        if not template.is_file():
            raise PdfGenerationError(f"Template não encontrado: {template}")
        try:
            with zipfile.ZipFile(template, "r") as package:
                entries = [(info, package.read(info.filename)) for info in package.infolist()]
            document = next(data for info, data in entries if info.filename == "word/document.xml")
            parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
            return etree.fromstring(document, parser), entries
        except (zipfile.BadZipFile, StopIteration, etree.XMLSyntaxError) as exc:
            raise PdfGenerationError(f"Template DOCX inválido: {template}") from exc

    @staticmethod
    def _write(
        destination: Path,
        root: Any,
        entries: list[tuple[zipfile.ZipInfo, bytes]],
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            standalone=True,
        )
        with zipfile.ZipFile(destination, "w") as package:
            for info, data in entries:
                package.writestr(info, document if info.filename == "word/document.xml" else data)

    @staticmethod
    def _find_control(root: Any, name: str) -> Any | None:
        for control in root.iter(f"{W}sdt"):
            properties = control.find(f"{W}sdtPr")
            if properties is None:
                continue
            tag = properties.find(f"{W}tag")
            alias = properties.find(f"{W}alias")
            values = {
                element.get(f"{W}val")
                for element in (tag, alias)
                if element is not None
            }
            if name in values:
                return control
        return None

    @staticmethod
    def _set_text(control: Any, value: str) -> None:
        properties = control.find(f"{W}sdtPr")
        if properties is not None:
            placeholder = properties.find(f"{W}showingPlcHdr")
            if placeholder is not None:
                properties.remove(placeholder)

        content = control.find(f"{W}sdtContent")
        if content is None:
            raise PdfGenerationError("Controle sem conteúdo")

        lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        block_paragraph = next(
            (child for child in content if child.tag == f"{W}p"),
            None,
        )
        if block_paragraph is not None:
            DocxContentControlRenderer._set_block_text(
                content,
                block_paragraph,
                lines,
            )
            return

        texts = list(content.iter(f"{W}t"))
        if not texts:
            raise PdfGenerationError("Controle sem elemento de texto")

        first = texts[0]
        for extra in texts[1:]:
            extra.text = ""
        run = first.getparent()
        first.text = ""
        first.set(XML_SPACE, "preserve")
        insert_at = run.index(first)
        for child in list(run)[insert_at + 1 :]:
            if child.tag in (f"{W}t", f"{W}br"):
                run.remove(child)

        first.text = lines[0]
        cursor = insert_at + 1
        for line in lines[1:]:
            run.insert(cursor, etree.Element(f"{W}br"))
            cursor += 1
            text = etree.Element(f"{W}t")
            text.set(XML_SPACE, "preserve")
            text.text = line
            run.insert(cursor, text)
            cursor += 1

    @staticmethod
    def _set_block_text(content: Any, template_paragraph: Any, lines: list[str]) -> None:
        template_runs = list(template_paragraph.iter(f"{W}r"))
        if not template_runs:
            raise PdfGenerationError("Controle em bloco sem elemento de texto")

        for child in list(content):
            content.remove(child)

        for line in lines:
            paragraph = copy.deepcopy(template_paragraph)
            runs = list(paragraph.iter(f"{W}r"))
            first_run = runs[0]
            for extra_run in runs[1:]:
                extra_run.getparent().remove(extra_run)
            for child in list(first_run):
                if child.tag != f"{W}rPr":
                    first_run.remove(child)
            text = etree.SubElement(first_run, f"{W}t")
            text.set(XML_SPACE, "preserve")
            text.text = line
            content.append(paragraph)

    @staticmethod
    def _set_direct_format(
        control: Any,
        *,
        font_family: str,
        size_half_points: str,
    ) -> None:
        properties = control.find(f"{W}sdtPr")
        if properties is not None:
            control_run_properties = properties.find(f"{W}rPr")
            if control_run_properties is None:
                control_run_properties = etree.Element(f"{W}rPr")
                properties.insert(0, control_run_properties)
            DocxContentControlRenderer._apply_run_format(
                control_run_properties,
                font_family,
                size_half_points,
            )

        content = control.find(f"{W}sdtContent")
        if content is None:
            raise PdfGenerationError("Controle sem conteúdo")
        for paragraph in content.iter(f"{W}p"):
            paragraph_properties = paragraph.find(f"{W}pPr")
            if paragraph_properties is None:
                paragraph_properties = etree.Element(f"{W}pPr")
                paragraph.insert(0, paragraph_properties)
            paragraph_run_properties = paragraph_properties.find(f"{W}rPr")
            if paragraph_run_properties is None:
                paragraph_run_properties = etree.SubElement(
                    paragraph_properties,
                    f"{W}rPr",
                )
            DocxContentControlRenderer._apply_run_format(
                paragraph_run_properties,
                font_family,
                size_half_points,
            )
        for run in content.iter(f"{W}r"):
            run_properties = run.find(f"{W}rPr")
            if run_properties is None:
                run_properties = etree.Element(f"{W}rPr")
                run.insert(0, run_properties)
            DocxContentControlRenderer._apply_run_format(
                run_properties,
                font_family,
                size_half_points,
            )

    @staticmethod
    def _apply_run_format(properties: Any, font_family: str, size_half_points: str) -> None:
        fonts = properties.find(f"{W}rFonts")
        if fonts is None:
            fonts = etree.Element(f"{W}rFonts")
            properties.insert(0, fonts)
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(f"{W}{attribute}", font_family)

        for element_name in ("sz", "szCs"):
            size = properties.find(f"{W}{element_name}")
            if size is None:
                size = etree.SubElement(properties, f"{W}{element_name}")
            size.set(f"{W}val", size_half_points)

    @staticmethod
    def _unwrap_content_controls(root: Any) -> None:
        """Remove populated Word controls so LibreOffice honors direct formatting."""
        for control in reversed(list(root.iter(f"{W}sdt"))):
            parent = control.getparent()
            content = control.find(f"{W}sdtContent")
            if parent is None or content is None:
                continue
            position = parent.index(control)
            for child in list(content):
                content.remove(child)
                parent.insert(position, child)
                position += 1
            parent.remove(control)

    @staticmethod
    def _refresh_ids(root: Any) -> None:
        for properties in root.iter(f"{W}sdtPr"):
            identifier = properties.find(f"{W}id")
            if identifier is not None:
                identifier.set(f"{W}val", str(random.randint(1, 2_000_000_000)))

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _half_points(size_points: float) -> str:
        return str(int(round(size_points * 2)))
