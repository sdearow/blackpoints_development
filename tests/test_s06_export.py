"""Test unitari per l'export dei risultati (Fase 5/6)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from src.s06_export import (
    esporta_classifica_excel,
    esporta_geojson,
    esporta_mappa_png,
    esporta_sintesi_csv,
    genera_sintesi,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _gdf_segmenti_finto(n: int = 50) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(42)
    fasce = rng.choice(
        ["monitoraggio", "bassa", "media", "alta", "altissima"], n
    )
    geom = [
        LineString([(12.4 + i * 0.001, 41.9), (12.4 + i * 0.001 + 0.0005, 41.9001)])
        for i in range(n)
    ]
    return gpd.GeoDataFrame(
        {
            "id_segmento": range(n),
            "toponimo": [f"Via {i}" for i in range(n)],
            "tipo_sito": "segmento",
            "n_incidenti": rng.poisson(5, n).astype(float),
            "n_mortali": rng.binomial(1, 0.02, n).astype(float),
            "n_feriti_gravi": rng.binomial(2, 0.05, n).astype(float),
            "n_feriti_lievi": rng.binomial(3, 0.3, n).astype(float),
            "n_solo_danni": rng.poisson(2, n).astype(float),
            "n_pedoni": rng.binomial(2, 0.1, n).astype(float),
            "EB_i": rng.uniform(2, 15, n),
            "excess_i": rng.normal(1, 3, n),
            "excess_EPDO_i": rng.normal(5, 10, n),
            "costo_sociale_eccesso_eur": rng.normal(50000, 80000, n),
            "A_norm": rng.uniform(0, 100, n),
            "B_norm": rng.uniform(0, 100, n),
            "C_norm": rng.uniform(0, 100, n),
            "D_norm": rng.uniform(0, 100, n),
            "ICP": rng.uniform(0, 100, n),
            "fascia_priorita": fasce,
            "quadrante_rischio": rng.choice(
                ["Q1_intervento_urgente", "Q2_intervento_programmato",
                 "Q3_indagine_approfondita", "Q4_monitoraggio"], n
            ),
            "v85_medio": rng.uniform(40, 80, n),
            "limite_velocita_medio": [50.0] * n,
            "tgm_medio": rng.uniform(500, 30000, n),
            "lunghezza_m": rng.uniform(100, 1000, n),
        },
        geometry=geom,
        crs="EPSG:32633",
    )


def _gdf_intersezioni_finto(n: int = 30) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(42)
    fasce = rng.choice(
        ["monitoraggio", "bassa", "media", "alta", "altissima"], n
    )
    geom = [Point(12.4 + i * 0.001, 41.9) for i in range(n)]
    return gpd.GeoDataFrame(
        {
            "id_nodo": range(n),
            "tipo_sito": "intersezione",
            "n_incidenti": rng.poisson(8, n).astype(float),
            "n_mortali": rng.binomial(1, 0.02, n).astype(float),
            "n_feriti_gravi": rng.binomial(2, 0.05, n).astype(float),
            "n_feriti_lievi": rng.binomial(3, 0.3, n).astype(float),
            "n_solo_danni": rng.poisson(3, n).astype(float),
            "n_pedoni": rng.binomial(3, 0.15, n).astype(float),
            "EB_i": rng.uniform(2, 15, n),
            "excess_i": rng.normal(1, 3, n),
            "excess_EPDO_i": rng.normal(5, 10, n),
            "costo_sociale_eccesso_eur": rng.normal(50000, 80000, n),
            "A_norm": rng.uniform(0, 100, n),
            "B_norm": rng.uniform(0, 100, n),
            "C_norm": rng.uniform(0, 100, n),
            "D_norm": rng.uniform(0, 100, n),
            "ICP": rng.uniform(0, 100, n),
            "fascia_priorita": fasce,
            "quadrante_rischio": rng.choice(
                ["Q1_intervento_urgente", "Q4_monitoraggio"], n
            ),
            "flusso_entrante": rng.uniform(1000, 50000, n),
            "is_semaforizzata": rng.choice([True, False], n),
            "n_archi": rng.choice([3, 4, 5], n),
        },
        geometry=geom,
        crs="EPSG:32633",
    )


# ---------------------------------------------------------------------------
# esporta_geojson
# ---------------------------------------------------------------------------


def test_esporta_geojson_crea_file(tmp_path: Path):
    gdf = _gdf_segmenti_finto(20)
    out = tmp_path / "test.geojson"
    esporta_geojson(gdf, out)
    assert out.exists()
    gdf_letto = gpd.read_file(out)
    assert len(gdf_letto) == 20
    assert gdf_letto.crs.to_epsg() == 4326


def test_esporta_geojson_colonne_selezionate(tmp_path: Path):
    gdf = _gdf_segmenti_finto(10)
    out = tmp_path / "test.geojson"
    esporta_geojson(gdf, out)
    gdf_letto = gpd.read_file(out)
    assert "ICP" in gdf_letto.columns
    assert "fascia_priorita" in gdf_letto.columns
    assert "geometry" in gdf_letto.columns


# ---------------------------------------------------------------------------
# esporta_classifica_excel
# ---------------------------------------------------------------------------


def test_esporta_excel_crea_file(tmp_path: Path):
    gdf = _gdf_segmenti_finto(30)
    out = tmp_path / "classifica.xlsx"
    esporta_classifica_excel(gdf, out)
    assert out.exists()
    df = pd.read_excel(out)
    assert len(df) == 30


def test_esporta_excel_ordinato_per_icp(tmp_path: Path):
    gdf = _gdf_segmenti_finto(50)
    out = tmp_path / "classifica.xlsx"
    esporta_classifica_excel(gdf, out)
    df = pd.read_excel(out)
    assert df["ranking"].iloc[0] == 1
    assert df["ICP"].iloc[0] >= df["ICP"].iloc[-1]


def test_esporta_excel_no_colonna_geometry(tmp_path: Path):
    gdf = _gdf_segmenti_finto(10)
    out = tmp_path / "classifica.xlsx"
    esporta_classifica_excel(gdf, out)
    df = pd.read_excel(out)
    assert "geometry" not in df.columns


# ---------------------------------------------------------------------------
# esporta_mappa_png
# ---------------------------------------------------------------------------


def test_esporta_mappa_png_crea_file(tmp_path: Path):
    gdf_seg = _gdf_segmenti_finto(20)
    gdf_int = _gdf_intersezioni_finto(10)
    out = tmp_path / "mappa.png"
    esporta_mappa_png(gdf_seg, gdf_int, out, dpi=72)
    assert out.exists()
    assert out.stat().st_size > 1000


# ---------------------------------------------------------------------------
# genera_sintesi
# ---------------------------------------------------------------------------


def test_genera_sintesi_struttura():
    gdf_seg = _gdf_segmenti_finto(100)
    gdf_int = _gdf_intersezioni_finto(50)
    df = genera_sintesi(gdf_seg, gdf_int)
    assert len(df) == 10  # 5 fasce x 2 tipi
    assert set(df.columns) == {
        "tipo_sito", "fascia_priorita", "n_siti", "n_incidenti_tot",
        "ICP_mediana", "ICP_max", "excess_EPDO_tot", "costo_sociale_tot_eur",
    }


def test_genera_sintesi_n_siti_coerente():
    gdf_seg = _gdf_segmenti_finto(100)
    gdf_int = _gdf_intersezioni_finto(50)
    df = genera_sintesi(gdf_seg, gdf_int)
    tot_seg = df.loc[df["tipo_sito"] == "segmento", "n_siti"].sum()
    tot_int = df.loc[df["tipo_sito"] == "intersezione", "n_siti"].sum()
    assert tot_seg == 100
    assert tot_int == 50


# ---------------------------------------------------------------------------
# esporta_sintesi_csv
# ---------------------------------------------------------------------------


def test_esporta_sintesi_csv_crea_file(tmp_path: Path):
    gdf_seg = _gdf_segmenti_finto(30)
    gdf_int = _gdf_intersezioni_finto(20)
    out = tmp_path / "sintesi.csv"
    esporta_sintesi_csv(gdf_seg, gdf_int, out)
    assert out.exists()
    df = pd.read_csv(out)
    assert len(df) == 10
