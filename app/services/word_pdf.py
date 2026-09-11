import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import PdfGenerationError


_WORD_LOCK = threading.Lock()


@dataclass(frozen=True)
class WordRenderJob:
    template: Path
    working_document: Path
    output_pdf: Path
    fields: dict[str, Any] = field(default_factory=dict)
    repeating_section: str | None = None
    repeating_rows: list[dict[str, Any]] | None = None


class WordPdfConverter:
    """Fills local templates and exports PDFs with a hidden Word Desktop instance."""

    def render_many(self, jobs: list[WordRenderJob]) -> None:
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise PdfGenerationError(
                "pywin32 não está disponível no interpretador da API: "
                f"{sys.executable}. Inicie pelo start.ps1 ou instale as dependências nesse ambiente"
            ) from exc

        with _WORD_LOCK:
            pythoncom.CoInitialize()
            word = None
            try:
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0
                for job in jobs:
                    if not job.template.is_file():
                        raise PdfGenerationError(f"Template não encontrado: {job.template}")
                    job.working_document.parent.mkdir(parents=True, exist_ok=True)
                    job.output_pdf.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(job.template, job.working_document)
                    document = word.Documents.Open(
                        str(job.working_document.resolve()),
                        ReadOnly=False,
                        AddToRecentFiles=False,
                    )
                    try:
                        self._fill_fields(document, job.fields)
                        if job.repeating_section is not None:
                            self._fill_repeating_section(
                                document,
                                job.repeating_section,
                                job.repeating_rows or [],
                            )
                        document.Save()
                        document.ExportAsFixedFormat(str(job.output_pdf.resolve()), 17)
                    finally:
                        document.Close(False)
                    if not job.output_pdf.is_file() or job.output_pdf.stat().st_size == 0:
                        raise PdfGenerationError(f"Word não gerou o PDF: {job.output_pdf.name}")
            except PdfGenerationError:
                raise
            except Exception as exc:
                raise PdfGenerationError(f"Falha na conversão local pelo Word: {exc}") from exc
            finally:
                if word is not None:
                    try:
                        word.Quit()
                    except Exception:
                        pass
                pythoncom.CoUninitialize()

    @classmethod
    def _fill_fields(cls, document: Any, fields: dict[str, Any]) -> None:
        for name, value in fields.items():
            control = cls._find_control(document.ContentControls, name)
            if control is None:
                raise PdfGenerationError(f"Controle '{name}' não encontrado no template")
            cls._set_text(control, value)

    @classmethod
    def _fill_repeating_section(
        cls,
        document: Any,
        section_name: str,
        rows: list[dict[str, Any]],
    ) -> None:
        section = cls._find_control(document.ContentControls, section_name)
        if section is None:
            raise PdfGenerationError(f"Seção repetitiva '{section_name}' não encontrada")
        if not rows:
            try:
                section.RepeatingSectionItems.Item(1).Delete()
            except Exception:
                for index in range(1, section.RepeatingSectionItems.Item(1).Range.ContentControls.Count + 1):
                    cls._set_text(section.RepeatingSectionItems.Item(1).Range.ContentControls.Item(index), "")
            return

        while section.RepeatingSectionItems.Count < len(rows):
            section.RepeatingSectionItems.Item(section.RepeatingSectionItems.Count).InsertItemAfter()
        while section.RepeatingSectionItems.Count > len(rows):
            section.RepeatingSectionItems.Item(section.RepeatingSectionItems.Count).Delete()

        for row_index, values in enumerate(rows, start=1):
            controls = section.RepeatingSectionItems.Item(row_index).Range.ContentControls
            for name, value in values.items():
                control = cls._find_control(controls, name)
                if control is None:
                    raise PdfGenerationError(
                        f"Controle repetitivo '{name}' não encontrado no template"
                    )
                cls._set_text(control, value)

    @staticmethod
    def _find_control(controls: Any, name: str) -> Any | None:
        for index in range(1, controls.Count + 1):
            control = controls.Item(index)
            if control.Title == name or control.Tag == name:
                return control
        return None

    @staticmethod
    def _set_text(control: Any, value: Any) -> None:
        try:
            control.LockContents = False
            control.LockContentControl = False
        except Exception:
            pass
        text = "" if value is None else str(value)
        control.Range.Text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\v")
