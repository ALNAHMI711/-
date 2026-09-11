from app.oauth_flow import OAuthProvider, build_authorization_url, validate_callback_state


def test_oauth_url_contains_required_parameters_and_state():
    provider = OAuthProvider(
        platform="example",
        authorization_endpoint="https://example.test/oauth/authorize",
        client_id="public-client-id",
        scopes=("profile", "publish"),
        redirect_uri="https://app.example.test/oauth/callback",
    )

    start = build_authorization_url(provider)

    assert start.state
    assert "client_id=public-client-id" in start.authorization_url
    assert "response_type=code" in start.authorization_url
    assert "state=" in start.authorization_url
    assert "scope=profile+publish" in start.authorization_url


def test_oauth_callback_state_must_match():
    assert validate_callback_state("abc", "abc")
    assert not validate_callback_state("abc", "wrong")
    assert not validate_callback_state("", "abc")
