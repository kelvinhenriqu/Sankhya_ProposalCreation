from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.proposal_pdf import GeneratedPdf


class FakePdfService:
    def generate(self, proposal, responsible: str, client_email: str) -> GeneratedPdf:
        assert proposal.Vendedor == "TESTE"
        assert responsible == "Responsável"
        assert client_email == "cliente@example.com"
        return GeneratedPdf(b"%PDF-1.4 test", "proposta teste.pdf")


def test_health_endpoint_starts_with_valid_environment(monkeypatch) -> None:
    monkeypatch.setenv("SANKHYA_CLIENT_ID", "test-client")
    monkeypatch.setenv("SANKHYA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SANKHYA_X_TOKEN", "test-x-token")
    monkeypatch.setenv("PDF_CONVERTER", "word")
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Correlation-ID"]
    finally:
        get_settings.cache_clear()


def test_web_interface_and_static_assets(monkeypatch) -> None:
    monkeypatch.setenv("SANKHYA_CLIENT_ID", "test-client")
    monkeypatch.setenv("SANKHYA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SANKHYA_X_TOKEN", "test-x-token")
    monkeypatch.setenv("PDF_CONVERTER", "word")
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            page = client.get("/")
            script = client.get("/static/app.js")
            stylesheet = client.get("/static/styles.css")
        assert page.status_code == 200
        assert 'id="proposal-form"' in page.text
        assert 'id="proposal-number"' in page.text
        assert script.status_code == 200
        assert "javascript" in script.headers["content-type"]
        assert stylesheet.status_code == 200
        assert "text/css" in stylesheet.headers["content-type"]
    finally:
        get_settings.cache_clear()


def test_pdf_endpoint_returns_download(monkeypatch) -> None:
    monkeypatch.setenv("SANKHYA_CLIENT_ID", "test-client")
    monkeypatch.setenv("SANKHYA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SANKHYA_X_TOKEN", "test-x-token")
    monkeypatch.setenv("PDF_CONVERTER", "word")
    get_settings.cache_clear()
    payload = {
        "proposta": {"Cabecalho": {"IdMemoria": "1"}, "Vendedor": "TESTE", "Itens": []},
        "responsavel": "Responsável",
        "email_cliente": "cliente@example.com",
    }

    try:
        with TestClient(app) as client:
            app.state.pdf_service = FakePdfService()
            response = client.post("/api/v1/proposals/pdf", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.4 test"
    finally:
        get_settings.cache_clear()
