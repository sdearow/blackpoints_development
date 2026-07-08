"""Test per equity_utils: Gini, Lorenz, concentration index, LISA, classi.

Casi a risultato noto, calcolati a mano o per costruzione.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.utils.equity_utils import (
    classifica_bivariata,
    concentration_index,
    curva_lorenz,
    equity_priority_zones,
    gini,
    lisa_bivariata,
)


class TestGiniLorenz:
    def test_distribuzione_uniforme_gini_zero(self):
        # Stessa dotazione pro-capite ovunque -> Gini = 0.
        dot = np.array([10.0, 20.0, 30.0])
        pop = np.array([100.0, 200.0, 300.0])
        assert gini(dot, pop) == pytest.approx(0.0, abs=1e-9)

    def test_concentrazione_totale(self):
        # Tutta la dotazione in una unita' su tante -> Gini -> 1.
        n = 1000
        dot = np.zeros(n)
        dot[0] = 100.0
        pop = np.ones(n)
        assert gini(dot, pop) > 0.99

    def test_gini_meta_popolazione(self):
        # Meta' popolazione senza nulla, meta' con tutto in parti uguali:
        # Gini teorico = 0.5.
        dot = np.array([0.0, 0.0, 50.0, 50.0])
        pop = np.array([1.0, 1.0, 1.0, 1.0])
        assert gini(dot, pop) == pytest.approx(0.5, abs=1e-9)

    def test_lorenz_estremi(self):
        dot = np.array([1.0, 2.0, 3.0])
        curva = curva_lorenz(dot, np.ones(3))
        assert curva["frac_pop"].iloc[0] == 0.0
        assert curva["frac_pop"].iloc[-1] == pytest.approx(1.0)
        assert curva["frac_dotazione"].iloc[-1] == pytest.approx(1.0)
        # Lorenz mai sopra la diagonale.
        assert (curva["frac_dotazione"] <= curva["frac_pop"] + 1e-12).all()

    def test_dotazione_nulla(self):
        assert gini(np.zeros(5), np.ones(5)) == pytest.approx(0.0)


class TestConcentrationIndex:
    def test_pro_bisogno_positivo(self):
        # Dotazione crescente col bisogno -> CI > 0.
        bisogno = np.array([1.0, 2.0, 3.0, 4.0])
        dot = np.array([1.0, 2.0, 3.0, 4.0])
        assert concentration_index(dot, bisogno, np.ones(4)) > 0

    def test_pro_avvantaggiati_negativo(self):
        # Dotazione decrescente col bisogno -> CI < 0 (iniquita' verticale).
        bisogno = np.array([1.0, 2.0, 3.0, 4.0])
        dot = np.array([4.0, 3.0, 2.0, 1.0])
        assert concentration_index(dot, bisogno, np.ones(4)) < 0

    def test_indipendente_dal_bisogno_zero(self):
        # Dotazione identica ovunque -> CI = 0 qualunque sia il bisogno.
        bisogno = np.array([1.0, 5.0, 2.0, 9.0])
        dot = np.array([3.0, 3.0, 3.0, 3.0])
        assert concentration_index(dot, bisogno, np.ones(4)) == pytest.approx(
            0.0, abs=1e-12
        )

    def test_antisimmetria(self):
        # Invertire il ranking di bisogno cambia segno al CI.
        rng = np.random.default_rng(42)
        bisogno = rng.uniform(0, 1, 50)
        dot = rng.uniform(0, 10, 50)
        pop = np.ones(50)
        ci_a = concentration_index(dot, bisogno, pop)
        ci_b = concentration_index(dot, -bisogno, pop)
        assert ci_a == pytest.approx(-ci_b, abs=1e-9)


def _griglia(n_lato: int, lato: float = 1000.0) -> gpd.GeoDataFrame:
    """Griglia quadrata n_lato x n_lato di celle."""
    celle = []
    for i in range(n_lato):
        for j in range(n_lato):
            x0, y0 = i * lato, j * lato
            celle.append(
                Polygon([(x0, y0), (x0 + lato, y0), (x0 + lato, y0 + lato), (x0, y0 + lato)])
            )
    return gpd.GeoDataFrame({"geometry": celle}, crs="EPSG:32633")


class TestLisaBivariata:
    def test_mismatch_rilevato(self):
        """Quadrante di celle ad alto bisogno e bassa dotazione in un
        contesto opposto -> cluster HL significativi in quell'angolo."""
        n = 10
        gdf = _griglia(n)
        # Bisogno alto nell'angolo 3x3 in basso a sinistra, dotazione invertita.
        bisogno, dotazione = [], []
        for i in range(n):
            for j in range(n):
                angolo = i < 3 and j < 3
                bisogno.append(10.0 if angolo else 1.0)
                dotazione.append(0.0 if angolo else 5.0)
        gdf["bisogno"] = bisogno
        gdf["dotazione"] = dotazione

        lisa = lisa_bivariata(gdf, "bisogno", "dotazione", k_vicini=8, seed=42)
        # Il centro dell'angolo (i=1,j=1 -> indice 11) deve essere HL significativo.
        centro_angolo = 1 * 10 + 1
        assert lisa.loc[centro_angolo, "lisa_quadrante"] == "HL"
        assert lisa.loc[centro_angolo, "lisa_sig"] == "HL"
        # E il grosso delle celle lontane non deve essere HL.
        lontane = [i * 10 + j for i in range(5, 10) for j in range(5, 10)]
        assert (lisa.loc[lontane, "lisa_quadrante"] != "HL").mean() > 0.9

    def test_riproducibile_col_seed(self):
        gdf = _griglia(6)
        rng = np.random.default_rng(0)
        gdf["b"] = rng.uniform(0, 1, len(gdf))
        gdf["d"] = rng.uniform(0, 1, len(gdf))
        l1 = lisa_bivariata(gdf, "b", "d", seed=7)
        l2 = lisa_bivariata(gdf, "b", "d", seed=7)
        pd.testing.assert_frame_equal(l1, l2)


class TestClassificazione:
    def test_classi_bivariate(self):
        bisogno = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype=float)
        dotazione = pd.Series([9, 8, 7, 6, 5, 4, 3, 2, 1], dtype=float)
        classe = classifica_bivariata(bisogno, dotazione, n_classi=3)
        # Bisogno massimo + dotazione minima -> "3-1".
        assert classe.iloc[-1] == "3-1"
        # Bisogno minimo + dotazione massima -> "1-3".
        assert classe.iloc[0] == "1-3"

    def test_priority_zones(self):
        bisogno = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9], dtype=float)
        dotazione = pd.Series([9, 8, 7, 6, 5, 4, 3, 2, 1], dtype=float)
        zone = equity_priority_zones(bisogno, dotazione)
        assert zone.iloc[-1]          # alto bisogno, bassa dotazione
        assert not zone.iloc[0]       # basso bisogno, alta dotazione

    def test_priority_zones_con_lisa(self):
        bisogno = pd.Series([1.0, 9.0])
        dotazione = pd.Series([5.0, 5.0])
        lisa = pd.DataFrame({"lisa_sig": ["ns", "HL"]})
        zone = equity_priority_zones(bisogno, dotazione, lisa=lisa)
        assert zone.iloc[1]
