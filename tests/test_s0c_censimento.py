"""Test per s0c_censimento: derivazione indicatori e join sezioni.

Fixture sintetiche con valori attesi calcolati a mano.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src.s0c_censimento import (
    deriva_indicatori,
    joina_sezioni_indicatori,
    valida_censimento,
)

CRS = "EPSG:32633"


def _riga_indicatori(sez_id: int, **kw) -> dict:
    """Riga del tracciato ISTAT con default a 0."""
    base = {c: 0 for c in (
        ["P1", "P14", "P15", "P16", "P27", "P28", "P29", "P83",
         "P86", "P87", "P88", "P101", "ST1", "PF1"]
        + [f"P{i}" for i in range(17, 27)]
    )}
    base["SEZ21_ID"] = sez_id
    base.update(kw)
    return base


@pytest.fixture
def indicatori_sintetici() -> pd.DataFrame:
    return pd.DataFrame([
        # Sezione 1: 100 abitanti, 20 bambini, 30 anziani, 10 stranieri,
        # base istruzione 80 di cui 40 con al piu' licenza media,
        # 50 in eta' 15-64 di cui 30 occupati.
        _riga_indicatori(
            1, P1=100, P14=10, P15=5, P16=5, P27=10, P28=10, P29=10,
            P83=80, P86=10, P87=10, P88=20, P17=50, P101=30, ST1=10, PF1=40,
        ),
        # Sezione 2: disabitata (tutto 0).
        _riga_indicatori(2),
    ])


@pytest.fixture
def sezioni_sintetiche() -> gpd.GeoDataFrame:
    # Quadrati 1 km x 1 km.
    def quadrato(x0):
        return Polygon([(x0, 0), (x0 + 1000, 0), (x0 + 1000, 1000), (x0, 1000)])
    return gpd.GeoDataFrame(
        {
            "SEZ21_ID": [1, 2, 3],
            "POP21": [100, 0, 0],
            "geometry": [quadrato(0), quadrato(2000), quadrato(4000)],
        },
        crs=CRS,
    )


class TestDerivaIndicatori:
    def test_quote_attese(self, indicatori_sintetici):
        out = deriva_indicatori(indicatori_sintetici).set_index("SEZ21_ID")
        assert out.loc[1, "perc_bambini"] == pytest.approx(0.20)
        assert out.loc[1, "perc_anziani"] == pytest.approx(0.30)
        assert out.loc[1, "perc_stranieri"] == pytest.approx(0.10)
        assert out.loc[1, "perc_istruzione_bassa"] == pytest.approx(40 / 80)
        assert out.loc[1, "perc_non_occupati"] == pytest.approx(1 - 30 / 50)

    def test_sezione_disabitata_tutte_quote_zero(self, indicatori_sintetici):
        out = deriva_indicatori(indicatori_sintetici).set_index("SEZ21_ID")
        for col in ("perc_bambini", "perc_anziani", "perc_stranieri",
                    "perc_istruzione_bassa", "perc_non_occupati"):
            assert out.loc[2, col] == 0.0

    def test_nessun_nan_o_inf(self, indicatori_sintetici):
        out = deriva_indicatori(indicatori_sintetici)
        num = out.select_dtypes(include=[float, int])
        assert np.isfinite(num.to_numpy()).all()


class TestJoin:
    def test_flag_e_riempimento(self, sezioni_sintetiche, indicatori_sintetici):
        der = deriva_indicatori(indicatori_sintetici)
        gdf = joina_sezioni_indicatori(sezioni_sintetiche, der)
        gdf = gdf.set_index("SEZ21_ID")
        # Sezione 1: abitata con indicatori.
        assert gdf.loc[1, "ha_indicatori"] and not gdf.loc[1, "pop_zero"]
        # Sezione 3: nel gpkg ma non negli indicatori -> disabitata, quote 0.
        assert not gdf.loc[3, "ha_indicatori"] and gdf.loc[3, "pop_zero"]
        assert gdf.loc[3, "perc_bambini"] == 0.0

    def test_area_e_densita(self, sezioni_sintetiche, indicatori_sintetici):
        der = deriva_indicatori(indicatori_sintetici)
        gdf = joina_sezioni_indicatori(sezioni_sintetiche, der).set_index("SEZ21_ID")
        assert gdf.loc[1, "area_km2"] == pytest.approx(1.0)
        assert gdf.loc[1, "densita_pop_km2"] == pytest.approx(100.0)

    def test_validazione(self, sezioni_sintetiche, indicatori_sintetici):
        der = deriva_indicatori(indicatori_sintetici)
        gdf = joina_sezioni_indicatori(sezioni_sintetiche, der)
        r = valida_censimento(gdf)
        assert r["n_sezioni"] == 3
        assert r["n_abitate"] == 1
        assert r["n_abitate_senza_indicatori"] == 0
        assert r["n_pop21_diverso_p1"] == 0
        assert r["pop_totale"] == 100
