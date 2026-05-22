from __future__ import annotations

import time
from typing import Any

import requests

from ._base_client import BaseApiClient


class SolscanError(RuntimeError):
    """Raised when Solscan returns an error or an unexpected payload."""


class SolscanClient(BaseApiClient):
    """Small wrapper around Solscan Pro API v2."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://pro-api.solscan.io/v2.0",
        timeout: int = 20,
        min_interval: float = 0.2,
        max_retries: int = 3,
        retry_sleep: float = 3.0,
    ) -> None:
        super().__init__(min_interval=min_interval, max_retries=max_retries, retry_sleep=retry_sleep, timeout=timeout)
        self.base_url = base_url.rstrip("/")
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
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            self._rate_limit()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._mark_request()
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._mark_request()
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise SolscanError(f"Cannot connect to Solscan: {exc}") from exc

            if response.status_code == 429:
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise SolscanError("Solscan rate limit reached; increase poll interval or lower limit")
            if response.status_code == 401:
                raise SolscanError(
                    "Solscan rejected this API key. Your current key is probably Free Level 1, "
                    "but this endpoint requires a higher API key level. Upgrade the Solscan API key "
                    "or switch this monitor to another data source."
                )
            if response.status_code >= 500:
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise SolscanError(f"Solscan HTTP {response.status_code}: {response.text[:300]}")
            if response.status_code >= 400:
                raise SolscanError(f"Solscan HTTP {response.status_code}: {response.text[:300]}")

            body = response.json()
            if isinstance(body, dict) and body.get("success") is False:
                raise SolscanError(f"Solscan API error: {body.get('message') or body}")
            if isinstance(body, dict) and "data" in body:
                return body["data"]
            return body
