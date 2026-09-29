import logging

from app.core.logging import SensitiveDataFilter


def test_sensitive_data_filter_masks_pipedrive_token_in_url() -> None:
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        "",
        0,
        "HTTP Request: GET https://example.pipedrive.com/api/v1/files?api_token=secret-value&term=21493",
        (),
        None,
    )

    assert SensitiveDataFilter().filter(record)
    assert "secret-value" not in record.getMessage()
    assert "api_token=[REDACTED]&term=21493" in record.getMessage()
