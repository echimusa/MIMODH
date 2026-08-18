"""MIMODH XSD schema tests."""
from pathlib import Path

import pytest

SCHEMA = Path(__file__).parent.parent / "schemas" / "mimodh_v1.xsd"


def test_schema_exists():
    assert SCHEMA.exists(), f"schema not found at {SCHEMA}"


def test_schema_parses():
    etree = pytest.importorskip("lxml.etree", reason="lxml not installed")
    etree.parse(str(SCHEMA))


def test_schema_is_valid_xsd():
    etree = pytest.importorskip("lxml.etree", reason="lxml not installed")
    schema = etree.XMLSchema(etree.parse(str(SCHEMA)))
    assert schema is not None


def test_schema_declares_three_tiers():
    text = SCHEMA.read_text(encoding="utf-8")
    for tier in ("Tier1", "Tier2", "Tier3"):
        assert tier in text, f"{tier} not declared in the schema"
