import pytest

from app.oauth_callback import (
    OAuthCallbackStatus,
    handle_oauth_callback,
    parse_callback_params,
)
from app.oauth_session import OAuthStateStore


def test_valid_callback_consumes_state_once():
    store = OAuthStateStore(ttl_seconds=600)
    state = store.create("YouTube", now=100.0)

    result = handle_oauth_callback(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        session_store=store,
        now=100.0,
    )

    assert result.status == OAuthCallbackStatus.LINKED
    assert result.success
    assert handle_oauth_callback(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        session_store=store,
        now=100.0,
    ).status == OAuthCallbackStatus.INVALID_STATE


def test_wrong_platform_is_rejected_before_consuming_state():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)

    result = handle_oauth_callback(
        platform="tiktok",
        expected_state=state,
        received_state=state.value,
        session_store=store,
        now=100.0,
    )

    assert result.status == OAuthCallbackStatus.INVALID_REQUEST
    assert store.consume(state, state.value, now=100.0)


def test_missing_state_is_rejected():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)

    result = handle_oauth_callback(
        platform="youtube",
        expected_state=state,
        received_state="",
        session_store=store,
        now=100.0,
    )

    assert result.status == OAuthCallbackStatus.INVALID_STATE


def test_provider_denial_is_reported_after_valid_state():
    store = OAuthStateStore()
    state = store.create("youtube", now=100.0)

    result = handle_oauth_callback(
        platform="youtube",
        expected_state=state,
        received_state=state.value,
        session_store=store,
        error="access_denied",
        error_description="المستخدم رفض التفويض.",
        now=100.0,
    )

    assert result.status == OAuthCallbackStatus.AUTHORIZATION_DENIED
    assert result.error == "المستخدم رفض التفويض."


def test_callback_parser_does_not_require_arbitrary_provider_fields():
    state, code, error, description = parse_callback_params(
        {"state": "abc", "code": "opaque-code", "unexpected": "ignored"}
    )
    assert (state, code, error, description) == ("abc", "opaque-code", None, None)


def test_callback_parser_extracts_provider_error():
    assert parse_callback_params(
        {"state": "abc", "error": "access_denied", "error_description": "Denied"}
    ) == ("abc", "", "access_denied", "Denied")
