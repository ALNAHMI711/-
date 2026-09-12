import pytest

from app.oauth_adapter import (
    OAuthAdapterConfig,
    OAuthConfigurationError,
    create_oauth_adapter,
)


def config() -> OAuthAdapterConfig:
    return OAuthAdapterConfig(
        client_id="public-client-id",
        authorization_endpoint="https://provider.example/authorize",
        redirect_uri="https://app.example/oauth/callback",
    )


def test_adapter_uses_registered_scopes_and_builds_authorization_url():
    adapter = create_oauth_adapter(" YouTube ", config())

    result = adapter.start()

    assert adapter.platform.key == "youtube"
    assert adapter.required_scopes() == (
        "https://www.googleapis.com/auth/youtube.upload",
    )
    assert "client_id=public-client-id" in result.authorization_url
    assert "response_type=code" in result.authorization_url
    assert "state=" in result.authorization_url
    assert result.state


def test_adapter_rejects_missing_public_configuration():
    with pytest.raises(OAuthConfigurationError):
        create_oauth_adapter(
            "youtube",
            OAuthAdapterConfig(
                client_id="",
                authorization_endpoint="https://provider.example/authorize",
                redirect_uri="https://app.example/oauth/callback",
            ),
        )


def test_adapter_does_not_expose_secret_fields():
    adapter = create_oauth_adapter("tiktok", config())
    assert "client_secret" not in repr(adapter).lower()
    assert "access_token" not in repr(adapter).lower()
