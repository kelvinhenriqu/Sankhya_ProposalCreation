from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from decimal import Decimal

from app.models.proposal import Proposal, ProposalHeader, ProposalItem
from app.services.proposal import ProposalService
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


def test_pipedrive_checks_by_proposal_id_and_creates_the_pdf_named_deal(monkeypatch) -> None:
    class FakePipedriveClient:
        enabled = True

        def __init__(self) -> None:
            self.searches: list[tuple[str, str]] = []
            self.creations: list[tuple[str, str, Decimal]] = []
            self.uploads: list[tuple[str, str, str, bytes]] = []

        def domain_for_company(self, company_code, company_name=None) -> str | None:
            assert company_code == "3"
            return "4xprocess"

        async def search_deals(self, domain: str, proposal_id: str):
            self.searches.append((domain, proposal_id))
            return [{"id": 99, "title": "21442 PCV - negocio existente"}]

        async def create_deal(self, domain: str, title: str, value: Decimal):
            self.creations.append((domain, title, value))
            return {"id": 100}

        async def upload_pdf(self, domain: str, deal_id: str, filename: str, content: bytes):
            self.uploads.append((domain, deal_id, filename, content))

    async def fake_get_proposal(self, proposal_id: int) -> Proposal:
        assert proposal_id == 21442
        return Proposal(
            Cabecalho=ProposalHeader(
                IdMemoria="21442", CodEmpresa="3", Cliente="Cliente", Revisao="1", ValorNota="1234,56",
            ),
            Vendedor="TESTE",
            Itens=[ProposalItem(DescricaoCompleta="Produto - descricao")],
        )

    monkeypatch.setenv("SANKHYA_CLIENT_ID", "test-client")
    monkeypatch.setenv("SANKHYA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SANKHYA_X_TOKEN", "test-x-token")
    monkeypatch.setenv("PDF_CONVERTER", "word")
    monkeypatch.setattr(ProposalService, "get_proposal", fake_get_proposal)
    get_settings.cache_clear()
    pipedrive = FakePipedriveClient()

    try:
        with TestClient(app) as client:
            app.state.pipedrive_client = pipedrive
            checked = client.get("/api/v1/proposals/21442/pipedrive/check")
            app.state.pdf_service = FakePdfService()
            created = client.post(
                "/api/v1/proposals/21442/pipedrive/pdf",
                params={"responsavel": "Responsável", "email_cliente": "cliente@example.com"},
            )
            attached = client.post(
                "/api/v1/proposals/21442/pipedrive/deals/99/pdf",
                params={"responsavel": "Responsável", "email_cliente": "cliente@example.com"},
            )

        assert checked.status_code == 200
        assert checked.json() == {
            "status": "existing",
            "message": None,
            "existing_deal": {
                "id": "99",
                "title": "21442 PCV - negocio existente",
                "url": "https://4xprocess.pipedrive.com/deal/99",
            },
        }
        assert created.status_code == 200
        assert created.content == b"%PDF-1.4 test"
        assert created.headers["x-pipedrive-deal-url"] == "https://4xprocess.pipedrive.com/deal/100"
        assert attached.status_code == 200
        assert attached.json()["attached"] is True
        assert attached.json()["deal"]["id"] == "99"
        assert pipedrive.searches == [
            ("4xprocess", "21442"),
            ("4xprocess", "21442"),
            ("4xprocess", "21442"),
        ]
        assert pipedrive.creations == [
            ("4xprocess", "21442 PCV - Cliente - Produto - REV 01", Decimal("1234.56")),
        ]
        assert pipedrive.uploads == [
            ("4xprocess", "100", "proposta teste.pdf", b"%PDF-1.4 test"),
            ("4xprocess", "99", "proposta teste.pdf", b"%PDF-1.4 test"),
        ]
    finally:
        get_settings.cache_clear()


def test_downloads_the_latest_matching_proposal_pdf_from_pipedrive(monkeypatch) -> None:
    class FakePipedriveClient:
        enabled = True

        def configured_domains(self) -> tuple[str, ...]:
            return ("4xprocess", "jtip")

        async def search_deals(self, domain: str, proposal_id: str):
            assert proposal_id == "21442"
            return [{"id": 99, "title": "21442 PCV - Cliente - Produto - REV 01"}]

        async def list_deal_files(self, domain: str, deal_id: str):
            assert domain == "4xprocess"
            assert deal_id == "99"
            return [
                {"id": 3, "name": "21442 PCV - Cliente - Produto - REV 01.pdf", "update_time": "2026-10-01"},
                {"id": 4, "name": "21442 PCV - Cliente - Produto - REV 02.pdf", "update_time": "2026-10-02"},
            ]

        @staticmethod
        def proposal_pdf(files, proposal_id: str):
            from app.clients.pipedrive import PipedriveClient
            return PipedriveClient.proposal_pdf(files, proposal_id)

        async def download_file(self, domain: str, file_id: str) -> bytes:
            assert file_id == "4"
            return b"%PDF-1.4 saved proposal"

    monkeypatch.setenv("SANKHYA_CLIENT_ID", "test-client")
    monkeypatch.setenv("SANKHYA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SANKHYA_X_TOKEN", "test-x-token")
    monkeypatch.setenv("PDF_CONVERTER", "word")
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            app.state.pipedrive_client = FakePipedriveClient()
            response = client.get("/api/v1/proposals/21442/pipedrive/download")
        assert response.status_code == 200
        assert response.content == b"%PDF-1.4 saved proposal"
        assert "21442 PCV" in response.headers["content-disposition"]
        assert response.headers["x-pipedrive-deal-url"] == "https://4xprocess.pipedrive.com/deal/99"
    finally:
        get_settings.cache_clear()
