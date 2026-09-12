import pytest

from app.account_connections import ConnectionState, VerificationState
from app.account_linking import AccountLinkingError, AccountLinkingService, LinkRequest
from app.oauth_callback import LinkedAccount


def account(account_id="yt-1", project_id="funny"):
    return LinkedAccount(
        account_id=account_id,
        platform="youtube",
        project_id=project_id,
        display_name="Funny Channel",
        permissions=("youtube.upload",),
    )


def test_link_enforces_project_ownership():
    service = AccountLinkingService()
    with pytest.raises(AccountLinkingError):
        service.link(LinkRequest(project_id="education", account=account()))


def test_link_and_project_scoped_read():
    service = AccountLinkingService()
    linked = service.link(LinkRequest(project_id="funny", account=account()))

    assert linked.project_id == "funny"
    assert service.get("funny", "yt-1") == linked
    assert service.get("education", "yt-1") is None
    assert service.list_for_project("funny") == (linked,)
    assert service.list_for_project("education") == ()


def test_duplicate_account_is_rejected():
    service = AccountLinkingService()
    service.link(LinkRequest(project_id="funny", account=account()))
    with pytest.raises(AccountLinkingError):
        service.link(LinkRequest(project_id="funny", account=account()))


def test_account_cannot_be_reused_by_another_project():
    service = AccountLinkingService()
    service.link(LinkRequest(project_id="funny", account=account()))
    with pytest.raises(AccountLinkingError):
        service.link(LinkRequest(project_id="education", account=account(project_id="education")))


def test_mark_verified_changes_only_verification_state():
    service = AccountLinkingService()
    linked = service.link(LinkRequest(project_id="funny", account=account()))
    verified = service.mark_verified("funny", "yt-1")

    assert linked.verification_state == VerificationState.NOT_CHECKED
    assert verified.verification_state == VerificationState.VERIFIED
    assert verified.connection_state == ConnectionState.CONNECTED
    assert verified.permissions == linked.permissions
    assert verified.ready_to_publish


def test_disconnect_is_project_scoped():
    service = AccountLinkingService()
    service.link(LinkRequest(project_id="funny", account=account()))
    with pytest.raises(AccountLinkingError):
        service.disconnect("education", "yt-1")
    disconnected = service.disconnect("funny", "yt-1")
    assert disconnected.connection_state == ConnectionState.DISCONNECTED
    assert not disconnected.ready_to_publish
