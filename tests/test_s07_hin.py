"""Test per s07_hin: HIN, curva di concentrazione, NKDE.

Fixture sintetiche con valori attesi calcolati a mano.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from src.s07_hin import (
    _kernel_quartico,
    calcola_ksi,
    calcola_ksi_km,
    calcola_nkde,
    costruisci_hin,
    curva_concentrazione,
    riaggancia_incidenti_intersezione,
)

CRS = "EPSG:32633"


@pytest.fixture
def segmenti_sintetici() -> gpd.GeoDataFrame:
    """10 segmenti da 1 km ciascuno con KSI noti [10,5,3,1,1,0,...,0].

    Totale KSI = 20. Con soglia 0.70: cumulata 10 (50%) -> 15 (75% >= 70%)
    -> HIN = primi 2 segmenti = 20% della rete.
    """
    ksi = [10, 5, 3, 1, 1, 0, 0, 0, 0, 0]
    righe = []
    for i, k in enumerate(ksi):
        righe.append(
            {
                "id_segmento": i,
                "n_incidenti": k * 2,   # meta' degli incidenti sono KSI
                "n_mortali": 0,
                "n_feriti": k,
                "lunghezza_m": 1000.0,
                "EB_i": float(k * 2),   # EB = osservato -> fattore 1
                "geometry": LineString([(i * 2000, 0), (i * 2000 + 1000, 0)]),
            }
        )
    return gpd.GeoDataFrame(righe, crs=CRS)


class TestKsi:
    def test_ksi_grezzo(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        assert list(ksi) == [10, 5, 3, 1, 1, 0, 0, 0, 0, 0]

    def test_ksi_eb_neutro_quando_eb_uguale_osservato(self, segmenti_sintetici):
        # EB_i = n_incidenti -> fattore di stabilizzazione = 1.
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=True)
        assert np.allclose(ksi, [10, 5, 3, 1, 1, 0, 0, 0, 0, 0])

    def test_ksi_eb_riscalatura(self, segmenti_sintetici):
        df = segmenti_sintetici.copy()
        # Sito 0: EB dimezza la frequenza osservata -> KSI stabilizzato 5.
        df.loc[0, "EB_i"] = df.loc[0, "n_incidenti"] / 2.0
        ksi = calcola_ksi(df, usa_eb=True)
        assert ksi.iloc[0] == pytest.approx(5.0)

    def test_ksi_km(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        ksi_km = calcola_ksi_km(segmenti_sintetici, ksi)
        # Lunghezza 1 km -> KSI/km == KSI.
        assert np.allclose(ksi_km, ksi)

    def test_lunghezza_zero_non_divide(self, segmenti_sintetici):
        df = segmenti_sintetici.copy()
        df.loc[0, "lunghezza_m"] = 0.0
        ksi = calcola_ksi(df, usa_eb=False)
        ksi_km = calcola_ksi_km(df, ksi)
        assert ksi_km.iloc[0] == 0.0
        assert np.isfinite(ksi_km).all()


class TestHin:
    def test_copertura_70(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        ksi_km = calcola_ksi_km(segmenti_sintetici, ksi)
        hin = costruisci_hin(segmenti_sintetici, ksi, ksi_km, soglia_copertura=0.70)
        # 10+5 = 15/20 = 75% >= 70% -> primi 2 segmenti.
        assert hin["is_hin"].sum() == 2
        assert hin.loc[0, "is_hin"] and hin.loc[1, "is_hin"]
        assert hin.loc[0, "rank_ksi"] == 1.0
        assert hin.loc[1, "rank_ksi"] == 2.0

    def test_ksi_zero_mai_in_hin(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        ksi_km = calcola_ksi_km(segmenti_sintetici, ksi)
        # Soglia 100%: tutti i positivi, mai gli zeri.
        hin = costruisci_hin(segmenti_sintetici, ksi, ksi_km, soglia_copertura=1.0)
        assert hin["is_hin"].sum() == 5
        assert not hin.loc[5:, "is_hin"].any()
        assert hin.loc[5:, "rank_ksi"].isna().all()

    def test_tutti_zero(self, segmenti_sintetici):
        df = segmenti_sintetici.copy()
        df["n_feriti"] = 0
        ksi = calcola_ksi(df, usa_eb=False)
        ksi_km = calcola_ksi_km(df, ksi)
        hin = costruisci_hin(df, ksi, ksi_km)
        assert not hin["is_hin"].any()


class TestCurvaConcentrazione:
    def test_monotona_e_terminale(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        ksi_km = calcola_ksi_km(segmenti_sintetici, ksi)
        curva = curva_concentrazione(segmenti_sintetici, ksi, ksi_km)
        assert (np.diff(curva["frac_rete"]) >= -1e-12).all()
        assert (np.diff(curva["frac_ksi"]) >= -1e-12).all()
        assert curva["frac_rete"].iloc[-1] == pytest.approx(1.0)
        assert curva["frac_ksi"].iloc[-1] == pytest.approx(1.0)

    def test_valore_intermedio(self, segmenti_sintetici):
        ksi = calcola_ksi(segmenti_sintetici, usa_eb=False)
        ksi_km = calcola_ksi_km(segmenti_sintetici, ksi)
        curva = curva_concentrazione(segmenti_sintetici, ksi, ksi_km)
        # Dopo 2 segmenti su 10 (20% rete) copertura = 15/20 = 75%.
        assert curva["frac_rete"].iloc[1] == pytest.approx(0.2)
        assert curva["frac_ksi"].iloc[1] == pytest.approx(0.75)


class TestKernel:
    def test_supporto_e_massa(self):
        u = np.linspace(-1.5, 1.5, 301)
        k = _kernel_quartico(u)
        assert (k[np.abs(u) > 1] == 0).all()
        # Integrale numerico su [-1,1] = 1.
        massa = np.trapezoid(k, u)
        assert massa == pytest.approx(1.0, abs=1e-3)


class TestNkde:
    def _segmento_unico(self, lunghezza=1000.0) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            [{"id_segmento": 0, "geometry": LineString([(0, 0), (lunghezza, 0)])}],
            crs=CRS,
        )

    def _incidente(self, x: float, peso: float = 1.0) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            [{"tipo_sito": "segmento", "id_sito": 0, "geometry": Point(x, 0)}],
            crs=CRS,
        )

    def test_massa_conservata(self):
        """L'integrale della densita' lungo la linea ~ peso dell'incidente
        (incidente centrale: kernel non troncato ai bordi)."""
        seg = self._segmento_unico(1000.0)
        inc = self._incidente(500.0)
        lixel, nkde_max = calcola_nkde(
            seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0,
            salva_solo_positivi=True,
        )
        massa = (lixel["nkde"] * 10.0).sum()
        assert massa == pytest.approx(1.0, rel=0.02)
        assert nkde_max.loc[0] > 0

    def test_picco_al_centro(self):
        seg = self._segmento_unico(1000.0)
        inc = self._incidente(500.0)
        lixel, _ = calcola_nkde(
            seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0,
        )
        picco = lixel.loc[lixel["nkde"].idxmax(), "offset_m"]
        assert picco == pytest.approx(500.0, abs=10.0)

    def test_simmetria(self):
        seg = self._segmento_unico(1000.0)
        inc = self._incidente(500.0)
        lixel, _ = calcola_nkde(seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0)
        lixel = lixel.set_index("offset_m").sort_index()
        # densita'(500-d) == densita'(500+d)
        for d in (15.0, 45.0, 95.0):
            assert lixel.loc[500 - d, "nkde"] == pytest.approx(
                lixel.loc[500 + d, "nkde"], rel=1e-6
            )

    def test_peso_scala_densita(self):
        seg = self._segmento_unico(1000.0)
        inc = self._incidente(500.0)
        lix1, _ = calcola_nkde(seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0)
        lix3, _ = calcola_nkde(
            seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0,
            pesi_incidenti=np.array([3.0]),
        )
        assert lix3["nkde"].max() == pytest.approx(3 * lix1["nkde"].max(), rel=1e-9)

    def test_incidenti_intersezione_esclusi_senza_snap(self):
        """Un incidente con tipo_sito='intersezione' non entra nella NKDE
        (il suo id_sito vive nello spazio degli id intersezione)."""
        seg = self._segmento_unico(1000.0)
        inc = gpd.GeoDataFrame(
            [{"tipo_sito": "intersezione", "id_sito": 0, "geometry": Point(500, 0)}],
            crs=CRS,
        )
        lixel, _ = calcola_nkde(seg, inc, lunghezza_lixel_m=10.0, bandwidth_m=100.0)
        assert len(lixel) == 0

    def test_riaggancio_intersezioni(self):
        seg = self._segmento_unico(1000.0)
        inc = gpd.GeoDataFrame(
            [
                # A 10 m dal segmento: riagganciato.
                {"tipo_sito": "intersezione", "id_sito": 99, "geometry": Point(500, 10)},
                # A 200 m: fuori raggio, escluso.
                {"tipo_sito": "intersezione", "id_sito": 98, "geometry": Point(500, 200)},
            ],
            crs=CRS,
        )
        out = riaggancia_incidenti_intersezione(inc, seg, raggio_snap_m=50.0)
        assert out.iloc[0]["tipo_sito"] == "segmento"
        assert out.iloc[0]["id_sito"] == 0
        assert pd.isna(out.iloc[1]["id_sito"])
        assert out.iloc[1]["tipo_sito"] == "intersezione"
