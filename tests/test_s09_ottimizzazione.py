"""Test per s09_ottimizzazione e optim_utils: MCLP con ottimo noto."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src.s09_ottimizzazione import (
    costruisci_candidati,
    costruisci_domanda,
    domanda_pesata,
    frontiera_pareto,
)
from src.utils.optim_utils import (
    costruisci_copertura,
    risolvi_mclp_esatto,
    risolvi_mclp_greedy,
)

CRS = "EPSG:32633"


class TestCopertura:
    def test_matrice(self):
        cand = np.array([[0.0, 0.0], [1000.0, 0.0]])
        dom = np.array([[100.0, 0.0], [900.0, 0.0], [5000.0, 0.0]])
        cop = costruisci_copertura(cand, dom, raggio_m=200.0)
        m = cop.toarray()
        # dom0 coperto solo da cand0, dom1 solo da cand1, dom2 da nessuno.
        assert m.tolist() == [[1, 0], [0, 1], [0, 0]]


class TestMclp:
    """Istanza a ottimo noto: 3 candidati, 4 punti di domanda.

    cand0 copre {d0 (10), d1 (10)} -> 20
    cand1 copre {d1 (10), d2 (15)} -> 25
    cand2 copre {d3 (5)}           -> 5
    p=1 -> ottimo cand1 (25). p=2 -> cand0+cand1 (35).
    """

    def _istanza(self):
        cand = np.array([[0.0, 0.0], [200.0, 0.0], [1000.0, 0.0]])
        dom = np.array([[50.0, 0.0], [100.0, 0.0], [250.0, 0.0], [1000.0, 50.0]])
        d = np.array([10.0, 10.0, 15.0, 5.0])
        cop = costruisci_copertura(cand, dom, raggio_m=120.0)
        return d, cop

    def test_greedy_p1(self):
        d, cop = self._istanza()
        ris = risolvi_mclp_greedy(d, cop, p=1)
        assert ris["scelti"] == [1]
        assert ris["domanda_coperta"] == pytest.approx(25.0)

    def test_greedy_p2(self):
        d, cop = self._istanza()
        ris = risolvi_mclp_greedy(d, cop, p=2)
        assert set(ris["scelti"]) == {0, 1}
        assert ris["domanda_coperta"] == pytest.approx(35.0)

    def test_esatto_uguale_greedy_su_istanza_semplice(self):
        d, cop = self._istanza()
        ris = risolvi_mclp_esatto(d, cop, p=2, timeout_s=30)
        assert ris["domanda_coperta"] == pytest.approx(35.0)
        assert ris["ottimo_garantito"]

    def test_budget_oltre_i_candidati_utili(self):
        d, cop = self._istanza()
        ris = risolvi_mclp_greedy(d, cop, p=10)
        # Copre tutto il copribile (d3 incluso) e si ferma.
        assert ris["domanda_coperta"] == pytest.approx(40.0)
        assert len(ris["scelti"]) == 3


class TestDomandaCandidati:
    def _sezioni(self):
        def q(x0):
            return Polygon([(x0, 0), (x0 + 100, 0), (x0 + 100, 100), (x0, 100)])
        return gpd.GeoDataFrame(
            {
                "SEZ21_ID": [1, 2, 3],
                "pop_zero": [False, False, True],
                "pop_totale": [100.0, 50.0, 0.0],
                "rischio_norm": [50.0, 0.0, 0.0],
                "vulnerabilita": [80.0, 20.0, 0.0],
                "equity_priority": [False, True, False],
                "geometry": [q(0), q(200), q(400)],
            },
            crs=CRS,
        )

    def test_costruisci_domanda(self):
        dom = costruisci_domanda(self._sezioni())
        # La sezione disabitata (e senza domanda) esce.
        assert list(dom["SEZ21_ID"]) == [1, 2]
        assert dom.geometry.geom_type.eq("Point").all()

    def test_domanda_pesata_estremi(self):
        dom = costruisci_domanda(self._sezioni())
        np.testing.assert_allclose(domanda_pesata(dom, 0.0), [50.0, 0.0])
        np.testing.assert_allclose(domanda_pesata(dom, 1.0), [80.0, 20.0])
        np.testing.assert_allclose(domanda_pesata(dom, 0.5), [65.0, 10.0])
        with pytest.raises(ValueError):
            domanda_pesata(dom, 1.5)

    def test_costruisci_candidati(self):
        seg = gpd.GeoDataFrame(
            {
                "id_segmento": [1, 2],
                "toponimo": ["A", "B"],
                "excess_EPDO_i": [5.0, 0.0],   # il secondo: eccesso 0
                "EB_i": [1.0, 0.5],
                "geometry": [Point(0, 0), Point(250, 50)],
            },
            crs=CRS,
        )
        inter = gpd.GeoDataFrame(
            {
                "id_nodo": [7],
                "toponimo": ["C"],
                "excess_EPDO_i": [9.0],
                "EB_i": [2.0],
                "geometry": [Point(5, 5)],
            },
            crs=CRS,
        )
        # Senza sezioni: solo il set rischio (eccesso > 0).
        cand = costruisci_candidati(seg, inter, n_candidati_rischio=10)
        assert len(cand) == 2
        assert cand.iloc[0]["id_sito"] == 7  # eccesso maggiore

        # Con le sezioni: il segmento 2 (eccesso 0 ma EB>0) entra come
        # candidato equita' perche' sta nella zona prioritaria.
        cand2 = costruisci_candidati(
            seg, inter, sezioni=self._sezioni(),
            n_candidati_rischio=10, n_candidati_equita=10,
        )
        assert len(cand2) == 3
        assert 2 in set(cand2["id_sito"])


class TestFrontiera:
    def test_estremi_coerenti(self):
        """A w=0 la copertura di rischio e' massima; a w=1 quella di
        bisogno e' massima (entro la tolleranza dell'euristica)."""
        rng = np.random.default_rng(42)
        n = 60
        xy = rng.uniform(0, 5000, size=(n, 2))
        dom = gpd.GeoDataFrame(
            {
                "SEZ21_ID": range(n),
                "rischio_norm": rng.uniform(0, 100, n),
                "vulnerabilita": rng.uniform(0, 100, n),
                "equity_priority": rng.uniform(0, 1, n) > 0.7,
                "pop_totale": rng.integers(50, 500, n).astype(float),
            },
            geometry=[Point(*p) for p in xy],
            crs=CRS,
        )
        cand = gpd.GeoDataFrame(
            {
                "id_sito": range(20),
                "toponimo": [f"c{i}" for i in range(20)],
                "tipo_sito": ["segmento"] * 20,
                "excess_EPDO_i": rng.uniform(1, 10, 20),
            },
            geometry=[Point(*p) for p in rng.uniform(0, 5000, size=(20, 2))],
            crs=CRS,
        )
        xy_dom = np.column_stack([dom.geometry.x, dom.geometry.y])
        xy_cand = np.column_stack([cand.geometry.x, cand.geometry.y])
        cop = costruisci_copertura(xy_cand, xy_dom, 800.0)

        scelte, frontiera = frontiera_pareto(
            dom, cand, cop, p=4, n_punti=5, metodo="greedy"
        )
        f = pd.DataFrame(frontiera)
        # Estremi: w=0 massimizza il rischio coperto, w=1 la vulnerabilita'.
        assert f.loc[0, "pct_rischio_coperto"] == f["pct_rischio_coperto"].max()
        assert (
            f.loc[len(f) - 1, "pct_vulnerabilita_coperta"]
            == f["pct_vulnerabilita_coperta"].max()
        )
        # Le scelte hanno tutte le colonne per la dashboard.
        for col in ("peso_equita", "ordine", "id_sito", "tipo_sito"):
            assert col in scelte.columns
