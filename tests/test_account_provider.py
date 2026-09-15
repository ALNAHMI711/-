import pytest

from app.account_provider import ProviderAPIError, verify_required_permissions


def test_required_permissions_are_verified_without_credentials():
    result = verify_required_permissions(("write", "read", "write"), ("read", "write"))

    assert result.verified is True
    assert result.missing_permissions == ()
    assert result.permissions == ("read", "write")


def test_missing_permissions_are_explicit():
    result = verify_required_permissions(("read",), ("read", "write"))

    assert result.verified is False
    assert result.missing_permissions == ("write",)


def test_provider_error_is_a_runtime_boundary():
    assert issubclass(ProviderAPIError, RuntimeError)
