"""Requested UI model control: session isolation, config choices and helper wiring."""
from pathlib import Path
import yaml
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app_test(path):
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from app.app import model_controls
with st.sidebar:
    client = model_controls({str(path)!r})
if client:
    st.text(client._model(None, 'large'))
"""
    return AppTest.from_string(script).run()


def test_dropdown_changes_session_client_without_rewriting_yaml(tmp_path):
    path = tmp_path / "params.yaml"
    config = {"llm": {"provider": "openai", "mode": "replay",
              "models": {"large": "first-model"}, "model_choices": ["first-model", "second-model"]}}
    path.write_text(yaml.safe_dump(config))
    before = path.read_bytes()
    first = app_test(path)
    assert not first.exception
    assert first.sidebar.selectbox[0].value == "first-model"
    first.sidebar.selectbox[0].select("second-model").run()
    assert not first.exception
    assert first.text[0].value == "second-model"
    assert path.read_bytes() == before
    other = app_test(path)
    assert other.sidebar.selectbox[0].value == "first-model"
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "data").exists()
    config["llm"]["model_choices"] = ["first-model"]
    path.write_text(yaml.safe_dump(config))
    first.run()
    assert not first.exception
    assert first.sidebar.selectbox[0].value == "first-model"


def test_selector_visible_even_without_rendered_filings():
    at = AppTest.from_file(str(ROOT / "app/app.py")).run()
    assert not at.exception
    assert at.sidebar.selectbox[0].label == "Model"
    assert at.sidebar.selectbox[0].value == "gpt-6-luna"
