from app.oauth_runtime import build_runtime_oauth


def test_runtime_oauth_is_disabled_without_provider_secrets(monkeypatch):
    for name in (
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "TIKTOK_CLIENT_ID",
        "TIKTOK_CLIENT_SECRET",
        "LINKEDIN_CLIENT_ID",
        "LINKEDIN_CLIENT_SECRET",
        "CREDENTIAL_VAULT_MASTER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    runtime = build_runtime_oauth()

    assert runtime.exchangers == {}
    assert runtime.providers == {}
    assert runtime.credential_vault is None


def test_runtime_oauth_builds_configured_provider_and_vault(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "youtube-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "youtube-secret")
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", "00" * 32)

    runtime = build_runtime_oauth()

    assert set(runtime.exchangers) == {"youtube"}
    assert set(runtime.providers) == {"youtube"}
    assert runtime.credential_vault is not None


def test_runtime_oauth_rejects_invalid_vault_key_without_affecting_provider(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "youtube-id")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "youtube-secret")
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", "not-a-hex-key")

    runtime = build_runtime_oauth()

    assert set(runtime.exchangers) == {"youtube"}
    assert set(runtime.providers) == {"youtube"}
    assert runtime.credential_vault is None
