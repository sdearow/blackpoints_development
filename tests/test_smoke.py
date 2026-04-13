"""Smoke test del progetto.

Verifica che:
1. ``config.yaml`` sia un YAML valido e contenga le sezioni principali.
2. Tutti i moduli ``src.*`` siano importabili senza errori di sintassi.
3. Il caricatore ``carica_config`` restituisca un dizionario non vuoto.

Questi test NON eseguono la logica di dominio (gli step sollevano
volutamente ``NotImplementedError``): servono solo a validare lo scaffolding.
"""

from __future__ import annotations

import importlib

import pytest

from src.config import carica_config

MODULI_PIPELINE = [
    "src.config",
    "src.s00_pulizia_incidenti",
    "src.s01_preparazione_rete",
    "src.s02_matching",
    "src.s03_spf",
    "src.s04_empirical_bayes",
    "src.s05_indice_composito",
    "src.s06_export",
    "src.utils.geo_utils",
    "src.utils.stats_utils",
    "src.utils.viz_utils",
]


@pytest.mark.parametrize("nome_modulo", MODULI_PIPELINE)
def test_import_modulo(nome_modulo: str) -> None:
    """Ogni modulo della pipeline deve essere importabile."""
    importlib.import_module(nome_modulo)


def test_config_si_carica() -> None:
    cfg = carica_config()
    assert isinstance(cfg, dict)
    assert cfg, "config.yaml e' vuoto"


def test_config_contiene_sezioni_principali() -> None:
    cfg = carica_config()
    sezioni_attese = {
        "periodo_analisi",
        "crs",
        "paths",
        "matching",
        "spf",
        "eb",
        "epdo",
        "indice_composito",
        "classificazione",
    }
    mancanti = sezioni_attese - cfg.keys()
    assert not mancanti, f"sezioni mancanti in config.yaml: {mancanti}"


def test_pesi_indice_composito_sommano_a_uno() -> None:
    cfg = carica_config()
    pesi = cfg["indice_composito"]["pesi"]
    totale = sum(pesi.values())
    assert abs(totale - 1.0) < 1e-9, f"i pesi dell'ICP devono sommare a 1, totale={totale}"
