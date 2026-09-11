class SankhyaError(Exception):
    """Base error for Sankhya communication or response failures."""


class SankhyaUnavailableError(SankhyaError):
    """Sankhya could not be reached after retry attempts."""


class SankhyaHTTPError(SankhyaError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Sankhya HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class SankhyaResponseError(SankhyaError):
    """Sankhya returned an invalid or unsuccessful application payload."""


class PdfGenerationError(Exception):
    """A proposal PDF could not be rendered or combined."""
