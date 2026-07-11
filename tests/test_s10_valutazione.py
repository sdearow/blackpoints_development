"""Test per s10_valutazione: formule Hauer, finestre, valutabilita'.

Il caso EB before-after e' verificato con valori calcolati a mano.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from src.s10_valutazione import (
    eb_before_after,
    finestre_temporali,
    siti_trattati,
    valuta_interventi,
)

CRS = "EPSG:32633"


class TestEbBeforeAfter:
    def test_caso_a_mano(self):
        """Un sito: E_pre=5, k=0.2, O_pre=10, E_post=2.5, O_post=4.

        w        = 1/(1+0.2*5) = 0.5
        EB_pre   = 0.5*5 + 0.5*10 = 7.5
        ratio    = 2.5/5 = 0.5
        pi       = 3.75
        Var(pi)  = 0.25 * 7.5 * 0.5 = 0.9375
        corr     = 1 + 0.9375/3.75^2 = 1.0667
        theta    = (4/3.75)/1.0667 = 1.0
        """
        ris = eb_before_after(
            o_pre=np.array([10.0]), o_post_tot=4.0,
            e_pre=np.array([5.0]), e_post=np.array([2.5]),
            k=np.array([0.2]),
        )
        assert ris["pi"] == pytest.approx(3.75)
        assert ris["theta"] == pytest.approx(1.0, rel=1e-6)
        assert ris["ic_low"] < 1.0 < ris["ic_high"]

    def test_riduzione_theta_minore_di_uno(self):
        # Il "dopo" osservato e' molto sotto il controfattuale.
        ris = eb_before_after(
            o_pre=np.array([20.0]), o_post_tot=2.0,
            e_pre=np.array([10.0]), e_post=np.array([10.0]),
            k=np.array([0.3]),
        )
        assert ris["theta"] < 1.0
        assert ris["theta"] > 0.0

    def test_zero_dopo(self):
        ris = eb_before_after(
            o_pre=np.array([10.0]), o_post_tot=0.0,
            e_pre=np.array([5.0]), e_post=np.array([5.0]),
            k=np.array([0.2]),
        )
        assert ris["theta"] == 0.0
        assert ris["ic_low"] == 0.0
        assert ris["ic_high"] > 0.0

    def test_spf_non_valida(self):
        ris = eb_before_after(
            o_pre=np.array([10.0]), o_post_tot=4.0,
            e_pre=np.array([0.0]),           # E_pre nullo: sito non usabile
            e_post=np.array([1.0]), k=np.array([0.2]),
        )
        assert ris["n_siti_validi"] == 0
        assert np.isnan(ris["theta"])

    def test_aggregazione_multi_sito(self):
        # Due siti identici: theta uguale al caso singolo con totali doppi.
        singolo = eb_before_after(
            o_pre=np.array([10.0]), o_post_tot=4.0,
            e_pre=np.array([5.0]), e_post=np.array([2.5]),
            k=np.array([0.2]),
        )
        doppio = eb_before_after(
            o_pre=np.array([10.0, 10.0]), o_post_tot=8.0,
            e_pre=np.array([5.0, 5.0]), e_post=np.array([2.5, 2.5]),
            k=np.array([0.2, 0.2]),
        )
        # Stesso rapporto O/pi; correzione minore (pi piu' grande) ->
        # theta leggermente piu' alto ma vicino.
        assert doppio["pi"] == pytest.approx(2 * singolo["pi"])
        assert doppio["theta"] == pytest.approx(singolo["theta"], rel=0.05)


class TestFinestre:
    def test_troncamento(self):
        fin = finestre_temporali(
            pd.Timestamp("2020-01-01"),
            data_min=pd.Timestamp("2018-06-01"),
            data_max=pd.Timestamp("2021-01-01"),
            n_anni_pre=3, n_anni_post=2,
        )
        # Pre chiesto dal 2017 ma i dati partono a giugno 2018.
        assert fin["pre_inizio"] == pd.Timestamp("2018-06-01")
        assert fin["anni_pre_eff"] == pytest.approx(1.58, abs=0.02)
        # Post chiesto fino al 2022 ma i dati finiscono a gennaio 2021.
        assert fin["anni_post_eff"] == pytest.approx(1.0, abs=0.01)

    def test_placeholder_futuro_post_zero(self):
        # Data di attivazione oltre la fine dei dati -> post nullo.
        fin = finestre_temporali(
            pd.Timestamp("2025-01-01"),
            data_min=pd.Timestamp("2018-01-01"),
            data_max=pd.Timestamp("2024-12-31"),
            n_anni_pre=3, n_anni_post=2,
        )
        assert fin["anni_post_eff"] == 0.0
        assert fin["anni_pre_eff"] > 2.9


class TestValutaInterventi:
    def _scenario(self, data_attivazione: str):
        interventi = gpd.GeoDataFrame(
            {
                "id_intervento": ["V:0001"],
                "tipo": ["velox"],
                "nome": ["test"],
                "fase": ["realizzato"],
                "data_attivazione": [pd.Timestamp(data_attivazione)],
                "data_stato": ["confermata"],
                "raggio_influenza_m": [500.0],
                "geometry": [Point(500, 0)],
            },
            crs=CRS,
        )
        segmenti = gpd.GeoDataFrame(
            {
                "id_segmento": [1],
                "E_i": [8.0],       # sul periodo SPF (4 anni) -> 2/anno
                "k_spf": [0.2],
                "geometry": [LineString([(0, 0), (1000, 0)])],
            },
            crs=CRS,
        )
        intersezioni = gpd.GeoDataFrame(
            {"id_nodo": [], "E_i": [], "k_spf": [],
             "geometry": gpd.GeoSeries([], crs=CRS)},
        )
        # 6 incidenti nel pre (2019-2021), 2 nel post (2022-2023):
        # l'ultimo estende data_max cosi' il post supera i 12 mesi minimi.
        date = (["2019-05-01", "2020-05-01", "2020-08-01",
                 "2021-02-01", "2021-06-01", "2021-11-01"]
                + ["2022-07-01", "2023-11-01"])
        incidenti = pd.DataFrame(
            {
                "tipo_sito": ["segmento"] * 8,
                "id_sito": [1] * 8,
                "data_ora": pd.to_datetime(date),
            }
        )
        attr = pd.concat([
            segmenti[["id_segmento", "E_i", "k_spf"]]
            .rename(columns={"id_segmento": "id_sito"}).assign(tipo_sito="segmento"),
        ], ignore_index=True)
        coppie = siti_trattati(interventi, segmenti, intersezioni)
        cfg = {"n_anni_pre": 3, "n_anni_post": 2,
               "mesi_minimi_pre": 24, "mesi_minimi_post": 12}
        return valuta_interventi(
            interventi, coppie, incidenti, attr, n_anni_spf=4.0, cfg=cfg
        )

    def test_data_reale_valutabile(self):
        out = self._scenario("2022-01-01")
        r = out.iloc[0]
        assert r["valutabile"]
        assert r["n_siti"] == 1
        assert r["O_pre"] == 6.0 and r["O_post"] == 2.0
        # Riduzione: 2 osservati contro un controfattuale piu' alto.
        assert r["theta"] < 1.0

    def test_data_placeholder_non_valutabile(self):
        # Attivazione oltre l'ultimo incidente disponibile (2022-07-01).
        out = self._scenario("2025-01-01")
        r = out.iloc[0]
        assert not r["valutabile"]
        assert r["motivo"] == "post_insufficiente"
        # Ma la struttura c'e': quando la data cambia, si valuta.
        assert r["n_siti"] == 1

    def test_intervento_isolato_senza_siti(self):
        interventi = gpd.GeoDataFrame(
            {
                "id_intervento": ["X:0001"], "tipo": ["velox"],
                "nome": [None], "fase": ["da_definire"],
                "data_attivazione": [pd.Timestamp("2022-01-01")],
                "data_stato": ["placeholder"],
                "raggio_influenza_m": [100.0],
                "geometry": [Point(99999, 99999)],
            },
            crs=CRS,
        )
        segmenti = gpd.GeoDataFrame(
            {"id_segmento": [1], "E_i": [8.0], "k_spf": [0.2],
             "geometry": [LineString([(0, 0), (1000, 0)])]},
            crs=CRS,
        )
        vuote = gpd.GeoDataFrame(
            {"id_nodo": [], "E_i": [], "k_spf": [],
             "geometry": gpd.GeoSeries([], crs=CRS)},
        )
        coppie = siti_trattati(interventi, segmenti, vuote)
        incidenti = pd.DataFrame(
            {"tipo_sito": ["segmento"], "id_sito": [1],
             "data_ora": [pd.Timestamp("2021-01-01")]}
        )
        attr = pd.DataFrame(
            {"tipo_sito": ["segmento"], "id_sito": [1],
             "E_i": [8.0], "k_spf": [0.2]}
        )
        out = valuta_interventi(
            interventi, coppie, incidenti, attr, 4.0,
            {"n_anni_pre": 3, "n_anni_post": 2,
             "mesi_minimi_pre": 24, "mesi_minimi_post": 12},
        )
        assert not out.iloc[0]["valutabile"]
        assert out.iloc[0]["motivo"] == "nessun_sito_trattato"


class TestDataFine:
    def test_cantiere_escluso_dal_dopo(self):
        """Con data_fine, il 'dopo' parte dalla fine lavori: il periodo
        di cantiere non entra in nessuna finestra."""
        fin = finestre_temporali(
            pd.Timestamp("2020-01-01"),          # inizio lavori
            data_min=pd.Timestamp("2015-01-01"),
            data_max=pd.Timestamp("2024-01-01"),
            n_anni_pre=3, n_anni_post=2,
            data_fine=pd.Timestamp("2020-07-01"),  # 6 mesi di cantiere
        )
        assert fin["pre_fine"] == pd.Timestamp("2020-01-01")
        assert fin["post_inizio"] == pd.Timestamp("2020-07-01")
        assert fin["anni_post_eff"] == pytest.approx(2.0, abs=0.01)

    def test_data_fine_assente_equivale_ad_attivazione(self):
        a = finestre_temporali(
            pd.Timestamp("2020-01-01"), pd.Timestamp("2015-01-01"),
            pd.Timestamp("2024-01-01"), 3, 2)
        b = finestre_temporali(
            pd.Timestamp("2020-01-01"), pd.Timestamp("2015-01-01"),
            pd.Timestamp("2024-01-01"), 3, 2, data_fine=pd.NaT)
        assert a == b

    def test_data_fine_precedente_errore(self):
        with pytest.raises(ValueError):
            finestre_temporali(
                pd.Timestamp("2020-01-01"), pd.Timestamp("2015-01-01"),
                pd.Timestamp("2024-01-01"), 3, 2,
                data_fine=pd.Timestamp("2019-01-01"))
