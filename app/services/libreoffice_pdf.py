import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.errors import PdfGenerationError
from app.services.docx_templates import DocxContentControlRenderer
from app.services.word_pdf import WordRenderJob


class LibreOfficePdfConverter:
    def __init__(self, executable: Path | None = None, timeout: int = 120):
        self._executable = self._find_executable(executable)
        self._timeout = timeout
        self._renderer = DocxContentControlRenderer()

    def render_many(self, jobs: list[WordRenderJob]) -> None:
        for job in jobs:
            if job.repeating_section is None:
                self._renderer.render(
                    job.template,
                    job.working_document,
                    job.fields,
                    font_size_points=job.field_font_size_points,
                    field_font_sizes=job.field_font_sizes,
                )
            else:
                self._renderer.render_repeating(
                    job.template,
                    job.working_document,
                    job.repeating_section,
                    job.repeating_rows or [],
                    fields=job.fields,
                    font_size_points=job.field_font_size_points,
                    field_font_sizes=job.field_font_sizes,
                )

        with tempfile.TemporaryDirectory(prefix="libreoffice-profile-") as profile_name:
            profile_uri = Path(profile_name).resolve().as_uri()
            command = [
                str(self._executable),
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(jobs[0].output_pdf.parent.resolve()),
                *[str(job.working_document.resolve()) for job in jobs],
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                    creationflags=creation_flags,
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfGenerationError(
                    f"LibreOffice excedeu o timeout de {self._timeout}s"
                ) from exc
            except OSError as exc:
                raise PdfGenerationError(f"Não foi possível executar LibreOffice: {exc}") from exc

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "sem detalhes").strip()[-1000:]
                raise PdfGenerationError(f"LibreOffice falhou: {detail}")
            for job in jobs:
                if not job.output_pdf.is_file() or job.output_pdf.stat().st_size == 0:
                    detail = (result.stdout or result.stderr or "sem detalhes").strip()[-1000:]
                    raise PdfGenerationError(
                        f"LibreOffice não gerou {job.output_pdf.name}: {detail}"
                    )

    @staticmethod
    def _find_executable(configured: Path | None) -> Path:
        candidates: list[Path] = []
        if configured:
            candidates.append(configured)
        discovered = shutil.which("soffice") or shutil.which("libreoffice")
        if discovered:
            candidates.append(Path(discovered))
        if os.name == "nt":
            candidates.extend(
                [
                    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
                    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
                ]
            )
        else:
            candidates.extend([Path("/usr/bin/libreoffice"), Path("/usr/bin/soffice")])
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        raise PdfGenerationError(
            "LibreOffice não encontrado. Configure LIBREOFFICE_EXECUTABLE"
        )
