"""Safe registry of platform capabilities used by the account-linking layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformDefinition:
    """Non-secret metadata for a supported publishing platform."""

    key: str
    display_name: str
    oauth_supported: bool
    required_scopes: tuple[str, ...] = ()
    monetization_status_supported: bool = False
    monetization_url: str | None = None


class UnsupportedPlatform(ValueError):
    """Raised when an unknown platform is requested."""


# Endpoints and client credentials deliberately do not live in this registry.
# Provider-specific OAuth adapters/configuration supply those values at runtime.
PLATFORMS: dict[str, PlatformDefinition] = {
    "youtube": PlatformDefinition(
        key="youtube",
        display_name="YouTube",
        oauth_supported=True,
        required_scopes=("https://www.googleapis.com/auth/youtube.upload",),
        monetization_status_supported=False,
        monetization_url="https://studio.youtube.com/channel/monetization",
    ),
    "tiktok": PlatformDefinition(
        key="tiktok",
        display_name="TikTok",
        oauth_supported=True,
        required_scopes=("video.publish",),
        monetization_status_supported=False,
        monetization_url="https://www.tiktok.com/creator-academy/en/monetization",
    ),
    "linkedin": PlatformDefinition(
        key="linkedin",
        display_name="LinkedIn",
        oauth_supported=True,
        required_scopes=("w_member_social",),
        monetization_status_supported=False,
    ),
}


def get_platform(key: str) -> PlatformDefinition:
    """Return a registered platform or raise a safe, explicit error."""
    normalized = key.strip().lower()
    try:
        return PLATFORMS[normalized]
    except KeyError as exc:
        raise UnsupportedPlatform(f"Unsupported platform: {normalized or '<empty>'}") from exc


def supported_platforms() -> tuple[PlatformDefinition, ...]:
    """Return registered platforms in deterministic order."""
    return tuple(PLATFORMS[key] for key in sorted(PLATFORMS))
