import logging
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import PipedriveError, PipedriveFileNotFoundError


logger = logging.getLogger(__name__)


class PipedriveClient:
    """Small backend-only client for the Pipedrive v2 Deals API."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PipedriveClient":
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self._settings.pipedrive_connect_timeout,
                read=self._settings.pipedrive_read_timeout,
                write=self._settings.pipedrive_write_timeout,
                pool=self._settings.pipedrive_connect_timeout,
            ),
            headers={
                "Accept": "application/json",
            },
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def enabled(self) -> bool:
        return self._settings.pipedrive_enabled

    @property
    def _token(self) -> str:
        token = self._settings.pipedrive_api_token
        return token.get_secret_value().strip() if token else ""

    def domain_for_company(self, company_code: Any, company_name: Any = None) -> str | None:
        code = str(company_code or "").strip()
        name = str(company_name or "").casefold()
        if code == "3" or "4x" in name:
            return self._normalize_domain(self._settings.pipedrive_domain_4x)
        if code in {"1", "2"} or "jtip" in name or "jt " in name:
            return self._normalize_domain(self._settings.pipedrive_domain_jtip)
        return None

    def configured_domains(self) -> tuple[str, ...]:
        """Return each configured company domain once, for read-only lookups."""
        domains = (
            self._normalize_domain(self._settings.pipedrive_domain_4x),
            self._normalize_domain(self._settings.pipedrive_domain_jtip),
        )
        return tuple(dict.fromkeys(domain for domain in domains if domain))

    async def search_deals(self, domain: str, proposal_id: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", domain, "/api/v2/deals/search",
            params={"term": proposal_id, "fields": "title"},
        )
        return self._deal_candidates(payload)

    async def create_deal(self, domain: str, title: str, value: Decimal) -> dict[str, Any]:
        payload = await self._request(
            "POST", domain, "/api/v2/deals",
            json={
                "title": title,
                "value": float(value),
                "currency": "BRL",
                "pipeline_id": self._settings.pipedrive_pipeline_id,
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise PipedriveError("Pipedrive retornou uma criacao sem ID do negocio")
        return data

    async def upload_pdf(self, domain: str, deal_id: str, filename: str, content: bytes) -> None:
        payload = await self._request(
            "POST",
            domain,
            "/api/v1/files",
            data={"deal_id": deal_id},
            files={"file": (filename, content, "application/pdf")},
        )
        if not isinstance(payload.get("data"), dict):
            raise PipedriveError("Pipedrive retornou um upload de arquivo invalido")

    async def list_deal_files(self, domain: str, deal_id: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", domain, f"/api/v1/deals/{deal_id}/files", params={"limit": 100}
        )
        files = payload.get("data")
        if files is None:
            return []
        if not isinstance(files, list):
            raise PipedriveError("Pipedrive retornou uma lista de arquivos invalida")
        return [file for file in files if isinstance(file, dict)]

    async def download_file(self, domain: str, file_id: str) -> bytes:
        """Download an attached PDF without exposing the Pipedrive token to clients."""
        if not self.enabled:
            raise PipedriveError("Integracao com Pipedrive nao configurada")
        if self._http is None:
            raise RuntimeError("PipedriveClient nao inicializado")
        try:
            response = await self._http.get(
                f"https://{domain}.pipedrive.com/api/v1/files/{file_id}/download",
                params={"api_token": self._token},
                headers={"Accept": "application/pdf"},
                follow_redirects=True,
            )
            logger.info(
                "pipedrive_request",
                extra={
                    "method": "GET",
                    "path": f"/api/v1/files/{file_id}/download",
                    "status_code": response.status_code,
                },
            )
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PipedriveError("Timeout ou indisponibilidade da API Pipedrive") from exc
        except httpx.HTTPStatusError as exc:
            raise PipedriveError(f"Pipedrive retornou HTTP {exc.response.status_code}") from exc
        content = response.content
        if not content.lstrip().startswith(b"%PDF-"):
            raise PipedriveError("O arquivo retornado pelo Pipedrive nao e um PDF valido")
        return content

    @staticmethod
    def proposal_pdf(files: list[dict[str, Any]], proposal_id: str) -> dict[str, Any]:
        """Select a PDF generated for this proposal, never an arbitrary attachment."""
        prefix = f"{proposal_id} pcv"
        candidates = [
            file for file in files
            if isinstance(file.get("id"), (str, int))
            and str(file.get("name") or file.get("file_name") or "").casefold().endswith(".pdf")
            and str(file.get("name") or file.get("file_name") or "").casefold().startswith(prefix)
        ]
        if not candidates:
            raise PipedriveFileNotFoundError("Nenhum PDF desta proposta foi encontrado no Pipedrive")
        return max(candidates, key=lambda file: str(file.get("update_time") or file.get("add_time") or ""))

    async def _request(self, method: str, domain: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.enabled:
            raise PipedriveError("Integracao com Pipedrive nao configurada")
        if self._http is None:
            raise RuntimeError("PipedriveClient nao inicializado")
        params = dict(kwargs.pop("params", {}))
        # API tokens are the authentication mechanism documented by Pipedrive.
        # Keep this server-side; do not expose it in frontend URLs or responses.
        params["api_token"] = self._token
        try:
            response = await self._http.request(
                method,
                f"https://{domain}.pipedrive.com{path}",
                params=params,
                **kwargs,
            )
            logger.info("pipedrive_request", extra={"method": method, "path": path, "status_code": response.status_code})
            response.raise_for_status()
            payload = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise PipedriveError("Timeout ou indisponibilidade da API Pipedrive") from exc
        except httpx.HTTPStatusError as exc:
            raise PipedriveError(f"Pipedrive retornou HTTP {exc.response.status_code}") from exc
        except ValueError as exc:
            raise PipedriveError("Pipedrive retornou JSON invalido") from exc
        if not isinstance(payload, dict):
            raise PipedriveError("Pipedrive retornou uma resposta inesperada")
        return payload

    @staticmethod
    def _normalize_domain(value: str) -> str:
        domain = value.strip().lower()
        domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        return domain.removesuffix(".pipedrive.com")

    @staticmethod
    def _deal_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
        # Search v2 returns data.items; accepting data directly also keeps the
        # parser compatible with the compact response used by some installations.
        data = payload.get("data")
        candidates = data.get("items", []) if isinstance(data, dict) else data
        if not isinstance(candidates, list):
            return []
        deals: list[dict[str, Any]] = []
        for candidate in candidates:
            item = candidate.get("item") if isinstance(candidate, dict) else None
            deal = item if isinstance(item, dict) else candidate
            if isinstance(deal, dict) and deal.get("id") and isinstance(deal.get("title"), str):
                deals.append(deal)
        return deals

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
