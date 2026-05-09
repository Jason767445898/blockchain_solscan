from __future__ import annotations

import time
from typing import Any

import requests


class SolscanError(RuntimeError):
    """Raised when Solscan returns an error or an unexpected payload."""


class SolscanClient:
    """Small wrapper around Solscan Pro API v2."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://pro-api.solscan.io/v2.0",
        timeout: int = 20,
        min_interval: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json",
                "token": api_key,
            }
        )

    def account_transactions(
        self,
        address: str,
        *,
        before: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "address": address,
            "limit": limit,
        }
        if before:
            params["before"] = before
        payload = self._get("/account/transactions", params=params)
        if not isinstance(payload, list):
            raise SolscanError("Expected a list from /account/transactions")
        return payload

    def transaction_detail(self, signature: str) -> dict[str, Any]:
        payload = self._get("/transaction/detail", params={"tx": signature})
        if not isinstance(payload, dict):
            raise SolscanError("Expected an object from /transaction/detail")
        return payload

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        self._last_request_at = time.monotonic()

        if response.status_code == 429:
            raise SolscanError("Solscan rate limit reached; increase poll interval or lower limit")
        if response.status_code == 401:
            raise SolscanError(
                "Solscan rejected this API key. Your current key is probably Free Level 1, "
                "but this endpoint requires a higher API key level. Upgrade the Solscan API key "
                "or switch this monitor to another data source."
            )
        if response.status_code >= 400:
            raise SolscanError(f"Solscan HTTP {response.status_code}: {response.text[:300]}")

        body = response.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise SolscanError(f"Solscan API error: {body.get('message') or body}")
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body
