import pytest

from app.platforms import get_platform, supported_platforms, UnsupportedPlatform


def test_registered_platform_has_safe_capabilities():
    youtube = get_platform(" YouTube ")
    assert youtube.key == "youtube"
    assert youtube.oauth_supported
    assert youtube.required_scopes
    assert "client_secret" not in repr(youtube).lower()


def test_unknown_platform_is_rejected():
    with pytest.raises(UnsupportedPlatform):
        get_platform("unknown-platform")


def test_supported_platforms_are_deterministic():
    platforms = supported_platforms()
    assert tuple(p.key for p in platforms) == ("linkedin", "tiktok", "youtube")
