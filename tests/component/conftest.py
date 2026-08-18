"""Fixtures for the Home Assistant component tests (require pytest-homeassistant-custom-component).

The pure tests (test_pure_units.py, test_ntp_pure.py) do NOT use these — they load modules by path
and run without the harness.
"""
import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA discover custom_components/gridwitness during tests."""
    yield
