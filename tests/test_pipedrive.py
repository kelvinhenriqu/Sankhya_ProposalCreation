import json
from decimal import Decimal

import httpx
import pytest

from app.clients.pipedrive import PipedriveClient
from app.core.config import Settings


@pytest.mark.asyncio
async def test_create_deal_uses_configured_pipeline() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"id": 123}})

    settings = Settings(
        sankhya_client_id="client",
        sankhya_client_secret="secret",
        sankhya_x_token="token",
        pipedrive_api_token="pipedrive-token",
        pipedrive_pipeline_id=8,
    )
    async with PipedriveClient(settings) as client:
        await client._http.aclose()  # type: ignore[union-attr]
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        created = await client.create_deal("4xprocess", "21493 PCV", Decimal("100.50"))

    assert created == {"id": 123}
    assert captured["payload"] == {
        "title": "21493 PCV",
        "value": 100.5,
        "currency": "BRL",
        "pipeline_id": 8,
    }
    assert "/api/v2/deals" in str(captured["url"])
