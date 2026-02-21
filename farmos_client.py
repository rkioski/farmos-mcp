import logging
import os
import sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [farmos-mcp] %(levelname)s %(message)s",
)

_client = None


class FarmOSClient:
    """Thin httpx wrapper around the farmOS JSON:API with manual OAuth2 token management."""

    def __init__(
        self,
        url: str,
        client_id: str,
        client_secret: str,
        username: str | None = None,
        password: str | None = None,
    ):
        self.base_url = url.rstrip("/")
        self.api_url = f"{self.base_url}/api"
        self._token_url = f"{self.base_url}/oauth/token"
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._http = httpx.Client(timeout=30.0)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _fetch_token(self) -> None:
        flow = "password" if (self._username and self._password) else "client_credentials"
        logging.info("AUTH fetching token via %s grant from %s", flow, self._token_url)
        if self._username and self._password:
            data = {
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._username,
                "password": self._password,
            }
        else:
            data = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }

        resp = self._http.post(self._token_url, data=data)
        logging.debug("AUTH token response: %s — body: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]
        logging.info("AUTH token acquired successfully")

    def _auth_headers(self) -> dict:
        if not self._access_token:
            self._fetch_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/vnd.api+json",
        }

    # ------------------------------------------------------------------
    # HTTP helpers — retry once on 401 (expired token)
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        params = kwargs.get("params")
        logging.debug("REQUEST %s %s params=%s", method, url, params)
        resp = self._http.request(method, url, headers=self._auth_headers(), **kwargs)
        logging.debug("RESPONSE %s %s — got %s, body preview: %s", method, url, resp.status_code, resp.text[:300])
        if resp.status_code == 401:
            logging.warning("RESPONSE 401 — re-authenticating and retrying")
            self._access_token = None
            resp = self._http.request(method, url, headers=self._auth_headers(), **kwargs)
            logging.debug("RESPONSE retry %s — %s", url, resp.status_code)
        resp.raise_for_status()
        return resp

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        return self._request("GET", url, params=params).json()

    def post(self, path: str, payload: dict) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/vnd.api+json"}
        return self._request("POST", url, json={"data": payload}, headers=headers).json()

    def patch(self, path: str, payload: dict) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/vnd.api+json"}
        return self._request("PATCH", url, json={"data": payload}, headers=headers).json()


# ------------------------------------------------------------------
# Singleton factory
# ------------------------------------------------------------------

def get_client() -> FarmOSClient:
    global _client
    if _client is None:
        _client = _create_client()
    return _client


def _create_client() -> FarmOSClient:
    url = os.environ.get("FARMOS_URL", "").rstrip("/")
    if not url:
        raise ValueError("FARMOS_URL is required")
    has_user = bool(os.environ.get("FARMOS_USERNAME"))
    has_pass = bool(os.environ.get("FARMOS_PASSWORD"))
    logging.info("CLIENT connecting to %s — username set: %s, password set: %s, read_only=%s",
                 url, has_user, has_pass, is_read_only())

    return FarmOSClient(
        url=url,
        client_id=os.environ.get("FARMOS_CLIENT_ID", "farm"),
        client_secret=os.environ.get("FARMOS_CLIENT_SECRET", ""),
        username=os.environ.get("FARMOS_USERNAME") or None,
        password=os.environ.get("FARMOS_PASSWORD") or None,
    )


def is_read_only() -> bool:
    return os.environ.get("FARMOS_READ_ONLY", "true").strip().lower() != "false"
