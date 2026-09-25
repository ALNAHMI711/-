from dataclasses import dataclass

from app.provider_http import LinkedInAccountProvider, TikTokAccountProvider, YouTubeAccountProvider


@dataclass
class Response:
    status_code: int
    payload: dict

    def json(self):
        return self.payload


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, *, headers, params):
        self.calls.append((url, headers, params))
        return self.response

    def post(self, url, *, headers, json):
        raise AssertionError("unexpected POST")


def test_youtube_provider_uses_authenticated_channel():
    transport = Transport(Response(200, {"items": [{"id": "UC123", "snippet": {"title": "My Channel"}}]}))
    account = YouTubeAccountProvider(transport).get_account("secret")
    assert account.account_id == "UC123"
    assert account.display_name == "My Channel"
    assert transport.calls[0][2] == {"part": "snippet", "mine": "true"}


def test_tiktok_provider_reads_v2_user_info():
    transport = Transport(Response(200, {"data": {"user": {"open_id": "open-123", "display_name": "Creator"}}}))
    account = TikTokAccountProvider(transport).get_account("secret")
    assert account.account_id == "open-123"
    assert account.display_name == "Creator"
    assert transport.calls[0][2]["fields"] == "open_id,display_name"


def test_linkedin_provider_reads_openid_subject():
    transport = Transport(Response(200, {"sub": "linkedin-123", "name": "Creator"}))
    account = LinkedInAccountProvider(transport).get_account("secret")
    assert account.account_id == "linkedin-123"
    assert account.display_name == "Creator"


def test_provider_identity_rejects_missing_identity():
    transport = Transport(Response(200, {"items": []}))
    try:
        YouTubeAccountProvider(transport).get_account("secret")
    except Exception as exc:
        assert "no YouTube channel" in str(exc)
    else:
        raise AssertionError("missing provider identity must fail")
