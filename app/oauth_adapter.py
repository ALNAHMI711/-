"""Provider-aware OAuth adapter primitives for secure account linking.

This module intentionally stops at authorization-start. Token exchange and token
storage belong to provider-specific infrastructure and must not be represented
as plaintext values in these models.
"""

from dataclasses import dataclass

from .oauth_flow import OAuthProvider, OAuthStart, build_authorization_url
from .platforms import PlatformDefinition, get_platform


@dataclass(frozen=True)
class OAuthAdapterConfig:
    """Runtime OAuth configuration containing public client metadata only."""

    client_id: str
    authorization_endpoint: str
    redirect_uri: str


class OAuthConfigurationError(ValueError):
    """Raised when an OAuth provider/configuration cannot safely start."""


class OAuthAdapter:
    """Build provider-specific OAuth authorization requests from the registry."""

    def __init__(self, platform: PlatformDefinition, config: OAuthAdapterConfig) -> None:
        if not platform.oauth_supported:
            raise OAuthConfigurationError(f"OAuth is not supported for {platform.key}")
        if not config.client_id.strip():
            raise OAuthConfigurationError("client_id is required")
        if not config.authorization_endpoint.strip():
            raise OAuthConfigurationError("authorization_endpoint is required")
        if not config.redirect_uri.strip():
            raise OAuthConfigurationError("redirect_uri is required")
        self._platform = platform
        self._config = config

    @property
    def platform(self) -> PlatformDefinition:
        return self._platform

    def required_scopes(self) -> tuple[str, ...]:
        """Return the scopes declared by the platform registry."""
        return self._platform.required_scopes

    def start(self) -> OAuthStart:
        """Create a CSRF state and authorization URL; do not exchange/store tokens."""
        provider = OAuthProvider(
            platform=self._platform.key,
            authorization_endpoint=self._config.authorization_endpoint,
            client_id=self._config.client_id,
            scopes=self.required_scopes(),
            redirect_uri=self._config.redirect_uri,
        )
        return build_authorization_url(provider)


def create_oauth_adapter(platform_key: str, config: OAuthAdapterConfig) -> OAuthAdapter:
    """Resolve a registered platform and create its OAuth adapter."""
    return OAuthAdapter(get_platform(platform_key), config)
