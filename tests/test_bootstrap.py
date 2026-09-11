from app.main import create_app


def test_application_bootstrap():
    result = create_app()
    assert result["status"] == "ok"
    assert result["name"]
