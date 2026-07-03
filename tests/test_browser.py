import socket
from unittest.mock import MagicMock

import pytest

from agent_harness.browser import read_web_page, validate_public_url


def resolver_for(address: str):
    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def test_public_https_url_is_accepted() -> None:
    url = "https://example.com/article"
    assert validate_public_url(url, resolver_for("93.184.216.34")) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "https://user:password@example.com/",
    ],
)
def test_unsafe_url_shapes_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_public_url(url, resolver_for("93.184.216.34"))


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_non_public_addresses_are_rejected(address: str) -> None:
    with pytest.raises(ValueError, match="privati"):
        validate_public_url("https://example.com/", resolver_for(address))


def test_read_web_page_truncates_large_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_harness.browser.validate_public_url",
        lambda url, resolver=socket.getaddrinfo: url,
    )

    large_chunk = b"a" * 50_000
    mock_response = MagicMock()
    mock_response.is_redirect = False
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes.return_value = [large_chunk]
    mock_response.__enter__ = lambda self: mock_response
    mock_response.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__enter__ = lambda self: mock_client
    mock_client.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        "agent_harness.browser.httpx.Client",
        lambda **kwargs: mock_client,
    )

    result = read_web_page("https://example.com/big", max_characters=1_000)

    assert "troncata per dimensione" in result
    assert "https://example.com/big" in result
    assert len(result) < 10_000

