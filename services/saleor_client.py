from __future__ import annotations

import threading
from typing import Any

import httpx

from core.config import get_settings

TOKEN_MUTATION = """
mutation($email: String!, $password: String!) {
  tokenCreate(email: $email, password: $password) {
    token
    errors { field message }
  }
}
"""


class SaleorError(RuntimeError):
    pass


class SaleorClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.saleor_api_url
        self.channel = settings.saleor_channel
        self.timeout = settings.saleor_timeout
        self.email = settings.saleor_email
        self.password = (
            settings.saleor_password.get_secret_value()
            if settings.saleor_password is not None
            else ""
        )
        token = settings.saleor_token
        self._token = token.get_secret_value() if token is not None else ""
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=self.timeout)

    def _login(self) -> str:
        response = self._client.post(
            self.url,
            json={
                "query": TOKEN_MUTATION,
                "variables": {"email": self.email, "password": self.password},
            },
        )
        response.raise_for_status()
        payload = response.json()
        result = (payload.get("data") or {}).get("tokenCreate") or {}
        token = result.get("token")
        if not token:
            raise SaleorError(f"Saleor 登录失败：{result.get('errors')}")
        return str(token)

    def _auth_headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        with self._lock:
            if not self._token:
                self._token = self._login()
            return {"Authorization": f"Bearer {self._token}"}

    def _post(self, query: str, variables: dict[str, Any]) -> httpx.Response:
        return self._client.post(
            self.url,
            json={"query": query, "variables": variables},
            headers=self._auth_headers(),
        )

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._post(query, variables)
        if response.status_code in (401, 403):
            with self._lock:
                self._token = ""
            response = self._post(query, variables)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise SaleorError(str(payload["errors"]))
        return payload.get("data") or {}


_client: SaleorClient | None = None
_client_lock = threading.Lock()


def get_saleor_client() -> SaleorClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = SaleorClient()
        return _client


def reset_saleor_client() -> None:
    global _client
    with _client_lock:
        _client = None
