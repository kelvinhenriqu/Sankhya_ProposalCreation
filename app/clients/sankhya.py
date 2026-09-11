import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import (
    SankhyaHTTPError,
    SankhyaResponseError,
    SankhyaUnavailableError,
)


logger = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class SankhyaClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.sankhya_base_url,
            timeout=httpx.Timeout(
                connect=settings.sankhya_connect_timeout,
                read=settings.sankhya_read_timeout,
                write=settings.sankhya_write_timeout,
                pool=settings.sankhya_pool_timeout,
            ),
            headers={"User-Agent": "sankhya-get-proposal/0.1"},
        )
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "SankhyaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempts = self._settings.sankhya_max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = await self._http.request(method, url, **kwargs)
                logger.info(
                    "sankhya_request",
                    extra={
                        "method": method,
                        "path": url.split("?", 1)[0],
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    },
                )
                if response.status_code not in _RETRYABLE_STATUS_CODES or attempt == attempts - 1:
                    return response
                delay = self._retry_delay(response, attempt)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "sankhya_transport_error",
                    extra={
                        "method": method,
                        "path": url.split("?", 1)[0],
                        "attempt": attempt + 1,
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt == attempts - 1:
                    break
                delay = self._settings.sankhya_retry_base_delay * (2**attempt)
            await asyncio.sleep(delay)

        raise SankhyaUnavailableError("Sankhya indisponível após as tentativas configuradas") from last_error

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return self._settings.sankhya_retry_base_delay * (2**attempt)

    async def _authenticate(self, force: bool = False) -> str:
        if not force and self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            if not force and self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token

            response = await self._send(
                "POST",
                "/authenticate",
                headers={
                    "X-Token": self._settings.sankhya_x_token,
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "client_id": self._settings.sankhya_client_id,
                    "client_secret": self._settings.sankhya_client_secret,
                    "grant_type": "client_credentials",
                },
            )
            self._raise_for_status(response)
            payload = self._parse_json(response)
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise SankhyaResponseError("Resposta de autenticação sem access_token")

            try:
                expires_in = max(int(payload.get("expires_in", 300)), 1)
            except (TypeError, ValueError):
                expires_in = 300
            refresh_margin = min(30, expires_in * 0.1)
            self._access_token = token
            self._token_expires_at = time.monotonic() + expires_in - refresh_margin
            return token

    async def _authorized_request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await self._authenticate()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        response = await self._send(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            self._access_token = None
            token = await self._authenticate(force=True)
            headers["Authorization"] = f"Bearer {token}"
            response = await self._send(method, url, headers=headers, **kwargs)
        self._raise_for_status(response)
        return response

    async def request_service(self, service_name: str, body: dict[str, Any], *, query: str = "") -> dict[str, Any]:
        url = f"/gateway/v1/mge/service.sbr?serviceName={service_name}&outputType=json{query}"
        response = await self._authorized_request(
            "POST",
            url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"serviceName": service_name, "requestBody": body},
        )
        payload = self._parse_json(response)
        self._ensure_service_success(payload)
        return payload

    async def get_product(self, product_code: Any) -> dict[str, Any]:
        response = await self._authorized_request(
            "GET",
            f"/v1/produtos/{product_code}",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        return self._parse_json(response)

    async def load_product_attachments(self, product_code: Any) -> dict[str, Any]:
        return await self.request_service(
            "Attach.load",
            {
                "criteria": {"codata": product_code, "sequencia": 0, "tipoAnexo": "R"},
                "clientEventList": {
                    "clientEvent": [{"$": "br.com.sankhya.mge.info.metro.cubico"}]
                },
            },
            query="&counter=383&application=ProdutoServico&preventTransform=false",
        )

    async def view_attachment(self, attachment: dict[str, Any]) -> dict[str, Any]:
        return await self.request_service(
            "Attach.view",
            {
                "anexo": {
                    "codata": attachment.get("CODATA"),
                    "sequencia": attachment.get("SEQUENCIA"),
                    "tipo": attachment.get("TIPO"),
                    "descricao": attachment.get("DESCRICAO"),
                    "tipoConteudo": attachment.get("TIPOCONTEUDO"),
                },
                "clientEventList": {
                    "clientEvent": [{"$": "br.com.sankhya.mge.info.metro.cubico"}]
                },
            },
            query="&application=ProdutoServico&preventTransform=false",
        )

    async def download_attachment(self, attachment_key: str) -> bytes:
        response = await self._authorized_request(
            "GET",
            "/gateway/v1/mge/visualizadorArquivos.mge"
            f"?hidemail=S&download=S&chaveArquivo={attachment_key}&responseType=arraybuffer",
            headers={"Accept": "application/pdf"},
        )
        content = response.content
        if not content.lstrip().startswith(b"%PDF-"):
            raise SankhyaResponseError("Conteúdo do anexo não é um PDF válido")
        return content

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SankhyaResponseError("Sankhya retornou JSON inválido") from exc
        if not isinstance(payload, dict):
            raise SankhyaResponseError("Sankhya retornou um objeto JSON inesperado")
        return payload

    @staticmethod
    def _ensure_service_success(payload: dict[str, Any]) -> None:
        status = payload.get("status")
        if status is not None and str(status) != "1":
            message = payload.get("statusMessage") or payload.get("message") or "Falha de serviço Sankhya"
            raise SankhyaResponseError(str(message))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        detail = response.text[:500] if response.content else "sem corpo"
        raise SankhyaHTTPError(response.status_code, detail)

