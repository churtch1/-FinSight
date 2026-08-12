from scripts.trigger_dashboard_snapshot import signed_dashboard_url


def test_signed_dashboard_url_matches_streamlit_auth_contract() -> None:
    url = signed_dashboard_url("https://example.streamlit.app/", "secret", 4102444800)

    assert url.startswith("https://example.streamlit.app/?auth=")
    assert url.endswith("&auth_exp=4102444800")
    assert "secret" not in url

