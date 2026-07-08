"""Test per s08_equita: vulnerabilita', rischio per sezione, dotazione, bisogno."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from src.s08_equita import (
    aggrega_rischio_sezioni,
    calcola_bisogno,
    calcola_dotazione,
    calcola_vulnerabilita,
)

CRS = "EPSG:32633"


def _quadrato(x0: float, lato: float = 1000.0) -> Polygon:
    return Polygon([(x0, 0), (x0 + lato, 0), (x0 + lato, lato), (x0, lato)])


@pytest.fixture
def sezioni() -> gpd.GeoDataFrame:
    """3 sezioni contigue da 1 km2: A [0,1km), B [1,2km), C [2,3km)."""
    return gpd.GeoDataFrame(
        {
            "pop_zero": [False, False, True],
            "pop_totale": [1000.0, 500.0, 0.0],
            "perc_bambini": [0.30, 0.10, 0.0],
            "perc_anziani": [0.10, 0.30, 0.0],
            "geometry": [_quadrato(0), _quadrato(1000), _quadrato(2000)],
        },
        crs=CRS,
    )


class TestVulnerabilita:
    def test_pesi_e_range(self, sezioni):
        vuln = calcola_vulnerabilita(
            sezioni, {"perc_bambini": 1.0, "perc_anziani": 1.0}
        )
        # Range 0-100, sezioni disabitate a 0.
        assert vuln.between(0, 100).all()
        assert vuln.iloc[2] == 0.0
        # Con pesi uguali A e B sono simmetriche -> stessa vulnerabilita'.
        assert vuln.iloc[0] == pytest.approx(vuln.iloc[1])

    def test_peso_sbilanciato(self, sezioni):
        vuln = calcola_vulnerabilita(sezioni, {"perc_bambini": 1.0})
        assert vuln.iloc[0] > vuln.iloc[1]

    def test_indicatore_mancante(self, sezioni):
        with pytest.raises(ValueError):
            calcola_vulnerabilita(sezioni, {"colonna_inesistente": 1.0})


class TestAggregaRischio:
    def test_segmento_ripartito_per_lunghezza(self, sezioni):
        # Segmento da 2 km con excess 10, a cavallo di A (1 km) e B (1 km):
        # 5 a testa. Intersezione con excess 3 dentro B.
        segmenti = gpd.GeoDataFrame(
            {"excess_EPDO_i": [10.0],
             "geometry": [LineString([(0, 500), (2000, 500)])]},
            crs=CRS,
        )
        intersezioni = gpd.GeoDataFrame(
            {"excess_EPDO_i": [3.0], "geometry": [Point(1500, 500)]},
            crs=CRS,
        )
        rischio = aggrega_rischio_sezioni(sezioni, segmenti, intersezioni)
        assert rischio.iloc[0] == pytest.approx(5.0)
        assert rischio.iloc[1] == pytest.approx(8.0)   # 5 + 3
        assert rischio.iloc[2] == pytest.approx(0.0)

    def test_excess_negativo_clippato(self, sezioni):
        # I siti piu' sicuri dell'atteso (excess < 0) non sottraggono rischio.
        segmenti = gpd.GeoDataFrame(
            {"excess_EPDO_i": [-4.0],
             "geometry": [LineString([(0, 500), (500, 500)])]},
            crs=CRS,
        )
        vuote = gpd.GeoDataFrame({"excess_EPDO_i": [], "geometry": []}, crs=CRS)
        rischio = aggrega_rischio_sezioni(sezioni, segmenti, vuote)
        assert (rischio == 0).all()


class TestDotazione:
    def test_buffer_puntuale_copre_sezioni_vicine(self, sezioni):
        # Velox a 100 m dal confine A|B con raggio 500: serve A e B, non C.
        interventi = gpd.GeoDataFrame(
            {
                "tipo": ["velox"],
                "raggio_influenza_m": [500.0],
                "geometry": [Point(900, 500)],
            },
            crs=CRS,
        )
        dot = calcola_dotazione(sezioni, interventi)
        assert dot["dot_totale"].tolist() == [1.0, 1.0, 0.0]
        assert dot["dot_velox"].tolist() == [1.0, 1.0, 0.0]

    def test_area_conta_per_impronta(self, sezioni):
        # Isola ambientale interna ad A (raggio 0): serve solo A.
        interventi = gpd.GeoDataFrame(
            {
                "tipo": ["isola_ambientale"],
                "raggio_influenza_m": [0.0],
                "geometry": [Polygon([(100, 100), (400, 100), (400, 400), (100, 400)])],
            },
            crs=CRS,
        )
        dot = calcola_dotazione(sezioni, interventi)
        assert dot["dot_totale"].tolist() == [1.0, 0.0, 0.0]

    def test_filtro_tipi(self, sezioni):
        interventi = gpd.GeoDataFrame(
            {
                "tipo": ["velox", "ciclabile"],
                "raggio_influenza_m": [400.0, 0.0],
                "geometry": [Point(500, 500),
                             LineString([(0, 100), (2900, 100)])],
            },
            crs=CRS,
        )
        dot = calcola_dotazione(sezioni, interventi, tipi=["velox"])
        assert "dot_ciclabile" not in dot.columns
        assert dot["dot_totale"].tolist() == [1.0, 0.0, 0.0]


class TestBisogno:
    def test_geometrica_richiede_entrambi(self):
        vuln = pd.Series([100.0, 100.0, 0.0])
        rischio = pd.Series([100.0, 0.0, 100.0])
        b = calcola_bisogno(vuln, rischio, metodo="geometrica")
        assert b.iloc[0] == pytest.approx(100.0)
        assert b.iloc[1] == 0.0
        assert b.iloc[2] == 0.0

    def test_pesata_non_annulla(self):
        vuln = pd.Series([100.0])
        rischio = pd.Series([0.0])
        b = calcola_bisogno(vuln, rischio, metodo="pesata", peso_rischio=0.5)
        assert b.iloc[0] == pytest.approx(50.0)

    def test_metodo_invalido(self):
        with pytest.raises(ValueError):
            calcola_bisogno(pd.Series([1.0]), pd.Series([1.0]), metodo="boh")
