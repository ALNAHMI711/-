from app.account_connections import (
    AccountConnection,
    ConnectionState,
    MonetizationState,
    VerificationState,
    monetization_readiness,
    verify_connection,
)


def test_connected_account_verifies_with_required_permissions():
    account = AccountConnection(
        account_id="yt-1",
        platform="youtube",
        display_name="مضحك",
        project_id="funny",
        connection_state=ConnectionState.CONNECTED,
        permissions=("upload", "analytics"),
    )

    result = verify_connection(account, ("upload",))

    assert result.state == VerificationState.VERIFIED
    assert result.missing_permissions == ()


def test_verified_account_is_publish_ready():
    account = AccountConnection(
        account_id="yt-2",
        platform="youtube",
        display_name="مضحك",
        project_id="funny",
        connection_state=ConnectionState.CONNECTED,
        verification_state=VerificationState.VERIFIED,
        permissions=("upload",),
    )

    assert account.ready_to_publish


def test_missing_permission_requires_user_action():
    account = AccountConnection(
        account_id="ig-1",
        platform="instagram",
        display_name="تعليم",
        project_id="education",
        connection_state=ConnectionState.CONNECTED,
        permissions=("analytics",),
    )

    result = verify_connection(account, ("publish",))

    assert result.state == VerificationState.ACTION_REQUIRED
    assert result.missing_permissions == ("publish",)


def test_monetization_never_guesses_without_official_status():
    result = monetization_readiness("youtube", None)

    assert result.state == MonetizationState.UNKNOWN
    assert result.actions


def test_official_monetization_status_is_normalized():
    result = monetization_readiness(
        "youtube",
        {"status": "enabled", "message": "مفعّل", "actions": []},
    )

    assert result.state == MonetizationState.ENABLED
    assert result.message == "مفعّل"
