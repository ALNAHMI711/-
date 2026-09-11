from app.health import health


def test_health_contract():
    result = health()
    assert result["status"] == "ok"
    assert result["service"]
