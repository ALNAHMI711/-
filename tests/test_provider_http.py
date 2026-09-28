from dataclasses import dataclass

from app.provider_http import LinkedInAccountProvider, TikTokAccountProvider, YouTubeAccountProvider


@dataclass
class Response:
    status_code: int
    payload: dict
    headers: dict | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}

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



def test_youtube_provider_lists_all_channels():
    transport = Transport(Response(200, {"items": [
        {"id": "UC1", "snippet": {"title": "One"}},
        {"id": "UC2", "snippet": {"title": "Two"}},
    ]}))
    accounts = YouTubeAccountProvider(transport).list_accounts("secret")
    assert [(a.account_id, a.display_name) for a in accounts] == [("UC1", "One"), ("UC2", "Two")]
    assert transport.calls[0][2]["maxResults"] == "50"


class UploadClient:
    def __init__(self):
        self.calls = []
        self.responses = [Response(308, {}, headers={"Range": "bytes=0-2"}), Response(201, {"id": "yt-1"})]

    def put(self, url, *, headers, content):
        self.calls.append((url, headers, content))
        return self.responses.pop(0)


def test_resumable_upload_chunk_handles_308_then_final_response():
    from app.provider_http import HttpxTransport

    client = UploadClient()
    offset, response = HttpxTransport._put_upload_chunk(
        client, "https://upload.example/session", b"abc", 0, 3,
        "video/mp4", {"Authorization": "Bearer token"}, 3,
    )
    assert offset == 3
    assert response is None
    assert len(client.calls) == 1
    assert client.calls[0][1]["Content-Range"] == "bytes 0-2/3"


def test_resumable_upload_chunk_retries_transient_failure():
    from app.provider_http import HttpxTransport

    class RetryClient:
        def __init__(self):
            self.calls = 0
        def put(self, url, *, headers, content):
            self.calls += 1
            if self.calls == 1:
                return Response(503, {})
            return Response(201, {"id": "yt-2"})

    client = RetryClient()
    offset, response = HttpxTransport._put_upload_chunk(
        client, "https://upload.example/session", b"abc", 0, 3,
        "video/mp4", {"Authorization": "Bearer token"}, 3,
    )
    assert client.calls == 2
    assert offset == 3
    assert response.status_code == 201
