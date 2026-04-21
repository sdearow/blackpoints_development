"""Test unitari per le Safety Performance Functions (Fase 2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.s03_spf import (
    accorpa_categorie,
    applica_predizioni,
    calibra_nb2,
    calibra_nb2_per_categoria,
    prepara_dataset_intersezioni,
    prepara_dataset_segmenti,
    riassumi_spf,
)


# ---------------------------------------------------------------------------
# Fixture sintetici
# ---------------------------------------------------------------------------


def _gdf_segmenti_finti() -> pd.DataFrame:
    """100 segmenti sintetici con attributi realistici."""
    rng = np.random.default_rng(42)
    n = 100
    return pd.DataFrame(
        {
            "id_segmento": range(n),
            "toponimo": [f"Via {i}" for i in range(n)],
            "lunghezza_m": rng.uniform(50, 500, n),
            "tgm_medio": rng.uniform(500, 30000, n),
            "v85_medio": rng.uniform(40, 80, n),
            "limite_velocita_medio": [50.0] * n,
            "eccesso_v85_medio": rng.uniform(-5, 15, n),
            "iqr_norm_medio": rng.uniform(0.05, 0.3, n),
            "classe_frc": rng.choice([2, 3, 4, 5], n),
            "pgtu_classifica": rng.choice(["S", "IQ", "Q", None], n),
            "grande_viabilita": [0.0] * n,
            "isolato": [False] * n,
        }
    )


def _gdf_matched_finti(n_seg: int, n_int: int) -> pd.DataFrame:
    """Incidenti sintetici abbinati a segmenti e intersezioni."""
    rng = np.random.default_rng(42)
    n_inc = 500
    rows = []
    for i in range(n_inc):
        if i < 300:
            mt = "segmento"
            im = rng.integers(0, n_seg)
        elif i < 450:
            mt = "intersezione"
            im = rng.integers(0, n_int)
        else:
            mt = "non_abbinato"
            im = pd.NA
        rows.append(
            {
                "id_incidente": i,
                "match_type": mt,
                "id_match": im,
                "n_morti": 1 if rng.random() < 0.005 else 0,
                "n_riservata": 1 if rng.random() < 0.02 else 0,
                "gravita": rng.choice(
                    ["solo_danni", "ferito_lieve", "mortale"],
                    p=[0.6, 0.38, 0.02],
                ),
                "natura_incidente": rng.choice(
                    ["Tamponamento", "Investimento di pedoni", "Scontro laterale"],
                    p=[0.5, 0.1, 0.4],
                ),
                "anno": rng.choice([2017, 2018, 2019, 2020, 2021]),
            }
        )
    return pd.DataFrame(rows)


def _gdf_intersezioni_finte(n: int = 50) -> pd.DataFrame:
    """Intersezioni sintetiche."""
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id_nodo": range(n),
            "n_archi": rng.choice([3, 4, 5], n),
            "archi": ["|".join(str(x) for x in rng.integers(1, 1000, 4)) for _ in range(n)],
            "is_semaforizzata": rng.choice([True, False], n, p=[0.3, 0.7]),
        }
    )


def _gdf_rete_finta() -> pd.DataFrame:
    """Rete finta con archi e TGM per il calcolo del flusso entrante."""
    return pd.DataFrame(
        {
            "id_arco": range(1, 1001),
            "tgm": np.random.default_rng(42).uniform(500, 30000, 1000),
        }
    )


# ---------------------------------------------------------------------------
# prepara_dataset_segmenti
# ---------------------------------------------------------------------------


def test_prepara_dataset_segmenti_conta_incidenti():
    seg = _gdf_segmenti_finti()
    matched = _gdf_matched_finti(n_seg=100, n_int=50)
    df = prepara_dataset_segmenti(seg, matched, n_anni=5.0)
    # Tutti i segmenti con TGM > 0 e lunghezza > 0 sono presenti.
    assert len(df) == 100
    # Il totale degli incidenti e' coerente.
    assert df["n_incidenti"].sum() == 300  # 300 segmento
    # Covariate logaritmiche presenti.
    assert "log_tgm" in df.columns
    assert "log_lunghezza" in df.columns
    assert "log_n_anni" in df.columns
    assert df["log_n_anni"].iloc[0] == pytest.approx(np.log(5.0))


def test_prepara_dataset_segmenti_filtra_tgm_zero():
    seg = _gdf_segmenti_finti()
    seg.loc[0, "tgm_medio"] = 0.0
    matched = _gdf_matched_finti(n_seg=100, n_int=50)
    df = prepara_dataset_segmenti(seg, matched, n_anni=5.0)
    assert 0 not in df["id_segmento"].values


# ---------------------------------------------------------------------------
# prepara_dataset_intersezioni
# ---------------------------------------------------------------------------


def test_prepara_dataset_intersezioni_conta_incidenti():
    intsz = _gdf_intersezioni_finte(50)
    matched = _gdf_matched_finti(n_seg=100, n_int=50)
    rete = _gdf_rete_finta()
    df = prepara_dataset_intersezioni(intsz, matched, rete, n_anni=5.0)
    assert len(df) == 50
    assert df["n_incidenti"].sum() == 150  # 150 intersezione
    assert "log_flusso_entrante" in df.columns
    assert "n_bracci" in df.columns


# ---------------------------------------------------------------------------
# accorpa_categorie
# ---------------------------------------------------------------------------


def test_accorpa_categorie_piccole_in_altro():
    df = pd.DataFrame(
        {
            "id": range(200),
            "cat": (["A"] * 100 + ["B"] * 80 + ["C"] * 10 + ["D"] * 10),
        }
    )
    out = accorpa_categorie(df, "cat", min_siti=50)
    assert set(out["categoria_spf"].unique()) == {"A", "B", "ALTRO"}
    assert (out["categoria_spf"] == "ALTRO").sum() == 20


def test_accorpa_categorie_nan_in_altro():
    df = pd.DataFrame({"id": [1, 2, 3], "cat": ["A", None, "A"]})
    out = accorpa_categorie(df, "cat", min_siti=1)
    assert out.loc[1, "categoria_spf"] == "ALTRO"


# ---------------------------------------------------------------------------
# calibra_nb2
# ---------------------------------------------------------------------------


def test_calibra_nb2_converge_su_dati_sintetici():
    rng = np.random.default_rng(42)
    n = 200
    log_tgm = rng.uniform(6, 10, n)
    log_lung = rng.uniform(-2, 1, n)
    mu = np.exp(0.5 + 0.8 * log_tgm + 0.5 * log_lung)
    y = rng.poisson(mu)
    df = pd.DataFrame(
        {
            "n_incidenti": y,
            "log_tgm": log_tgm,
            "log_lunghezza": log_lung,
            "log_n_anni": [np.log(5)] * n,
        }
    )
    ris = calibra_nb2(df, ["log_tgm", "log_lunghezza"])
    assert ris["converged"]
    assert ris["n_siti"] == n
    # I coefficienti devono essere positivi (concordi col modello generativo).
    assert ris["coefficienti"]["log_tgm"] > 0
    assert ris["coefficienti"]["log_lunghezza"] > 0
    assert len(ris["predetti"]) == n


def test_calibra_nb2_troppi_pochi_siti():
    df = pd.DataFrame(
        {
            "n_incidenti": [1, 2],
            "log_tgm": [7.0, 8.0],
            "log_n_anni": [1.0, 1.0],
        }
    )
    ris = calibra_nb2(df, ["log_tgm"])
    assert not ris["converged"]


# ---------------------------------------------------------------------------
# calibra_nb2_per_categoria
# ---------------------------------------------------------------------------


def test_calibra_nb2_per_categoria_separa():
    rng = np.random.default_rng(42)
    n = 100
    df = pd.DataFrame(
        {
            "n_incidenti": rng.poisson(5, n),
            "log_tgm": rng.uniform(7, 10, n),
            "log_n_anni": [np.log(5)] * n,
            "cat": ["A"] * 60 + ["B"] * 40,
        }
    )
    risultati = calibra_nb2_per_categoria(df, "cat", ["log_tgm"])
    assert "A" in risultati
    assert "B" in risultati
    assert risultati["A"]["n_siti"] == 60
    assert risultati["B"]["n_siti"] == 40


# ---------------------------------------------------------------------------
# applica_predizioni
# ---------------------------------------------------------------------------


def test_applica_predizioni_aggiunge_E_i():
    rng = np.random.default_rng(42)
    n = 100
    df = pd.DataFrame(
        {
            "n_incidenti": rng.poisson(5, n),
            "log_tgm": rng.uniform(7, 10, n),
            "log_n_anni": [np.log(5)] * n,
            "categoria_spf": ["A"] * n,
        }
    )
    risultati = calibra_nb2_per_categoria(df, "categoria_spf", ["log_tgm"])
    df_out = applica_predizioni(df, risultati, "categoria_spf")
    assert "E_i" in df_out.columns
    assert "k_spf" in df_out.columns
    assert df_out["E_i"].notna().sum() == n


# ---------------------------------------------------------------------------
# riassumi_spf
# ---------------------------------------------------------------------------


def test_riassumi_spf_struttura():
    ris_seg = {"A": {"n_siti": 100, "converged": True, "alpha": 0.5, "k": 2.0, "coefficienti": {"const": 1.0}}}
    ris_int = {"sem": {"n_siti": 50, "converged": True, "alpha": 0.3, "k": 3.3, "coefficienti": {"const": 0.5}}}
    r = riassumi_spf(ris_seg, ris_int)
    assert "segmenti" in r
    assert "intersezioni" in r
    assert r["segmenti"]["A"]["n_siti"] == 100
    assert r["intersezioni"]["sem"]["converged"]
