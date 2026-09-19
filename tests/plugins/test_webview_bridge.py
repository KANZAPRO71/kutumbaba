from persona_ai.plugins.webview_bridge import handle_ui_mode_change, normalize_ui_mode


def test_normalize_ui_mode_aliases():
    assert normalize_ui_mode("BELAJAR_BAKU") == "study"
    assert normalize_ui_mode("Cerita aja") == "cerita_tong"
    assert normalize_ui_mode("teman_jalan") == "teman_jalan"


def test_handle_ui_mode_change_no_session():
    out = handle_ui_mode_change("nongkrong")
    assert out["ok"] is True
    assert out["mode"] == "nongkrong"
    assert out["applied"] is False
