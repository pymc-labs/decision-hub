"""Unit tests for GitHub App installation token minting."""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

# Generate a throwaway RSA key pair for testing
from cryptography.hazmat.primitives.asymmetric import rsa

from decision_hub.infra.github_app_token import clear_token_cache, mint_installation_token

_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PEM = _TEST_PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()

TEST_APP_ID = "123456"
TEST_INSTALLATION_ID = "789012"


@pytest.fixture(autouse=True)
def _isolate_token_cache():
    """Each test starts with an empty cache so cache state never leaks across tests."""
    clear_token_cache()
    yield
    clear_token_cache()


class TestMintInstallationToken:
    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_returns_token_on_success(self, mock_post: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_fake_installation_token"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False)

        assert result == "ghs_fake_installation_token"
        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_jwt_payload_is_correct(self, mock_post: MagicMock):
        """Verify the JWT contains correct iss, iat, and exp claims."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_tok"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        before = int(time.time())
        mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False)
        after = int(time.time())

        # Extract the JWT from the Authorization header
        call_kwargs = mock_post.call_args
        auth_header = call_kwargs.kwargs["headers"]["Authorization"]
        encoded_jwt = auth_header.removeprefix("Bearer ")

        decoded = jwt.decode(
            encoded_jwt,
            TEST_PUBLIC_KEY,
            algorithms=["RS256"],
            options={"verify_exp": False},
        )

        assert decoded["iss"] == TEST_APP_ID
        # iat should be ~60s before call time
        assert before - 120 <= decoded["iat"] <= after
        # exp should be ~10 min after iat
        assert decoded["exp"] - decoded["iat"] == 11 * 60  # 60s back + 10 min forward

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_calls_correct_url(self, mock_post: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_tok"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False)

        url = mock_post.call_args.args[0]
        assert url == f"https://api.github.com/app/installations/{TEST_INSTALLATION_ID}/access_tokens"

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_raises_on_http_error(self, mock_post: MagicMock):
        """Should propagate httpx.HTTPStatusError on API failure."""
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False)


class TestTokenCaching:
    """Repeated calls within the cache TTL must reuse the same token."""

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_second_call_uses_cache(self, mock_post: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_cached"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        first = mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID)
        second = mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID)

        assert first == second == "ghs_cached"
        assert mock_post.call_count == 1

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_different_installations_are_cached_separately(self, mock_post: MagicMock):
        tokens = iter([{"token": "tok-A"}, {"token": "tok-B"}])

        def side_effect(*_args, **_kwargs):
            resp = MagicMock()
            resp.json.return_value = next(tokens)
            resp.raise_for_status = MagicMock()
            return resp

        mock_post.side_effect = side_effect

        a = mint_installation_token(TEST_APP_ID, TEST_PEM, "111")
        b = mint_installation_token(TEST_APP_ID, TEST_PEM, "222")

        assert a == "tok-A"
        assert b == "tok-B"
        assert mock_post.call_count == 2

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_use_cache_false_bypasses_and_does_not_pollute(self, mock_post: MagicMock):
        responses = iter([{"token": "fresh-1"}, {"token": "fresh-2"}, {"token": "cached"}])

        def side_effect(*_args, **_kwargs):
            resp = MagicMock()
            resp.json.return_value = next(responses)
            resp.raise_for_status = MagicMock()
            return resp

        mock_post.side_effect = side_effect

        # Two uncached calls always hit the network.
        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False) == "fresh-1"
        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID, use_cache=False) == "fresh-2"

        # A subsequent cached call mints once more and then reuses the value.
        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID) == "cached"
        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID) == "cached"
        assert mock_post.call_count == 3

    @patch("decision_hub.infra.github_app_token.httpx.post")
    def test_clear_token_cache_forces_remint(self, mock_post: MagicMock):
        responses = iter([{"token": "one"}, {"token": "two"}])

        def side_effect(*_args, **_kwargs):
            resp = MagicMock()
            resp.json.return_value = next(responses)
            resp.raise_for_status = MagicMock()
            return resp

        mock_post.side_effect = side_effect

        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID) == "one"
        clear_token_cache()
        assert mint_installation_token(TEST_APP_ID, TEST_PEM, TEST_INSTALLATION_ID) == "two"
        assert mock_post.call_count == 2
