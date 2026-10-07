"""Tests for the OJ Microline Thermostat integration."""

from pathlib import Path


def load_fixture(name: str) -> str:
    """Load a JSON fixture with an OJ Microline API response."""
    return (Path(__file__).parent / "fixtures" / name).read_text()
