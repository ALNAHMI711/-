"""Framework-neutral OAuth flow primitives for platform account linking."""

from dataclasses import dataclass
from urllib.parse import urlencode
from secrets import token_urlsafe


@dataclass(frozen=True)
class OAuthProvider:
    platform: str
    authorization_endpoint: str
    client_id: str
    scopes: tuple[str, ...]
    redirect_uri: str


@dataclass(frozen=True)
class OAuthStart:
    state: str
    authorization_url: str


def build_authorization_url(provider: OAuthProvider) -> OAuthStart:
    """Build an OAuth authorization URL; the actual token exchange belongs to the adapter."""
    state = token_urlsafe(32)
    params = {
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "response_type": "code",
        "scope": " ".join(provider.scopes),
        "state": state,
    }
    return OAuthStart(state=state, authorization_url=f"{provider.authorization_endpoint}?{urlencode(params)}")


def validate_callback_state(expected: str, received: str) -> bool:
    """Reject OAuth callbacks whose CSRF state does not match the server session."""
    return bool(expected) and bool(received) and expected == received
