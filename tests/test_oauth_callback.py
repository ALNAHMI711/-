from datetime import datetime, timezone

from app.account_linking import AccountLinkingService
from app.account_provider import ProviderAccount, ProviderVerification
from app.credential_vault import InMemoryCredentialVault
from app.oauth_callback import (
    OAuthCallbackStatus,
    complete_oauth_link,
    handle_oauth_callback,
    parse_callback_params,
)
from app.oauth_session import OAuthStateStore
from app.oauth_token_exchange import OAuthTokenBundle


class FakeExchanger:
    def __init__(self):
        self.calls = []

    def exchange_code(self, code, redirect_uri):
        self.calls.append((code, redirect_uri))
        return OAuthTokenBundle(
            access_token="access-secret",
            token_type="Bearer",
            refresh_token="refresh-secret",
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            scope=("scope.write",),
        )


class FakeProvider:
    def get_account(self, access_token):
        assert access_token == "access-secret"
        return ProviderAccount("channel-1", "My Channel", ("scope.read", "scope.write"))

    def verify_permissions(self, access_token, required_permissions):
        assert access_token == "access-secret"
        return ProviderVerification(True, tuple(required_permissions))


def test_valid_callback_consumes_state_once():
    store = OAuthStateStore(ttl_seconds=600)
    state = store.create("YouTube", now=100.0)
    result = handle_oauth_callback(platform="youtube", expected_state=state, received_state=state.value, session_store=store, now=100.0)
    assert result.status == OAuthCallbackStatus.LINKED
    assert result.success
    assert handle_oauth_callback(platform="youtube", expected_state=state, received_state=state.value, session_store=store, now=100.0).status == OAuthCallbackStatus.INVALID_STATE


def test_wrong_platform_is_rejected_before_consuming_state():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)
    result = handle_oauth_callback(platform="tiktok", expected_state=state, received_state=state.value, session_store=store, now=100.0)
    assert result.status == OAuthCallbackStatus.INVALID_REQUEST
    assert store.consume(state, state.value, now=100.0)


def test_missing_state_is_rejected():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)
    result = handle_oauth_callback(platform="youtube", expected_state=state, received_state="", session_store=store, now=100.0)
    assert result.status == OAuthCallbackStatus.INVALID_STATE


def test_provider_denial_is_reported_after_valid_state():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)
    result = handle_oauth_callback(platform="youtube", expected_state=state, received_state=state.value, session_store=store, error="access_denied", error_description="المستخدم رفض التفويض.", now=100.0)
    assert result.status == OAuthCallbackStatus.AUTHORIZATION_DENIED
    assert result.error == "المستخدم رفض التفويض."


def test_callback_parser_does_not_require_arbitrary_provider_fields():
    assert parse_callback_params({"state": "abc", "code": "opaque-code", "unexpected": "ignored"}) == ("abc", "opaque-code", None, None)


def test_callback_parser_extracts_provider_error():
    assert parse_callback_params({"state": "abc", "error": "access_denied", "error_description": "Denied"}) == ("abc", "", "access_denied", "Denied")


def test_complete_callback_exchanges_server_side_stores_secret_and_links_safe_metadata():
    states = OAuthStateStore()
    state = states.create("youtube", now=100.0, user_id="admin", project_id="project-1")
    exchanger = FakeExchanger()
    vault = InMemoryCredentialVault()
    accounts = AccountLinkingService()
    completion = complete_oauth_link(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        code="one-time-code",
        redirect_uri="https://example.test/oauth/callback/youtube",
        state_store=states,
        exchanger=exchanger,
        provider=FakeProvider(),
        vault=vault,
        account_service=accounts,
        required_permissions=("scope.write",),
        now=100.0,
    )
    assert completion.result.status == OAuthCallbackStatus.LINKED
    assert exchanger.calls == [("one-time-code", "https://example.test/oauth/callback/youtube")]
    assert completion.result.credential is not None
    assert completion.result.credential.credential_id.startswith("cred_")
    assert completion.result.account is not None
    assert completion.result.account.account_id == "channel-1"
    assert accounts.get("project-1", "channel-1") is not None
    assert vault.get_secret(completion.result.credential) == ("access-secret", "refresh-secret")
    assert "access-secret" not in repr(completion.result.account)


def test_complete_callback_rejects_token_scope_missing_required_permission():
    states = OAuthStateStore()
    state = states.create("youtube", now=100.0, user_id="admin", project_id="project-1")
    vault = InMemoryCredentialVault()

    class ScopeLimitedExchanger(FakeExchanger):
        def exchange_code(self, code, redirect_uri):
            return OAuthTokenBundle(
                access_token="access-secret",
                token_type="Bearer",
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                scope=("scope.read",),
            )

    result = complete_oauth_link(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        code="code",
        redirect_uri="https://example.test/oauth/callback/youtube",
        state_store=states,
        exchanger=ScopeLimitedExchanger(),
        provider=FakeProvider(),
        vault=vault,
        account_service=AccountLinkingService(),
        required_permissions=("scope.write",),
        now=100.0,
    )
    assert result.result.status == OAuthCallbackStatus.PROVIDER_ERROR
    assert result.result.credential is None


def test_complete_callback_does_not_store_credentials_when_permissions_fail():
    class MissingProvider(FakeProvider):
        def verify_permissions(self, access_token, required_permissions):
            return ProviderVerification(False, (), ("scope.write",), "missing")

    states = OAuthStateStore()
    state = states.create("youtube", now=100.0, user_id="admin", project_id="project-1")
    vault = InMemoryCredentialVault()
    result = complete_oauth_link(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        code="code",
        redirect_uri="https://example.test/oauth/callback/youtube",
        state_store=states,
        exchanger=FakeExchanger(),
        provider=MissingProvider(),
        vault=vault,
        account_service=AccountLinkingService(),
        required_permissions=("scope.write",),
        now=100.0,
    )
    assert result.result.status == OAuthCallbackStatus.PROVIDER_ERROR
    assert result.result.credential is None
