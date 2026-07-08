"""Test per s0d_interventi: normalizzazione sorgenti, fasi, date, raggi."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from src.s0d_interventi import (
    applica_date,
    assegna_raggio_influenza,
    carica_sorgente,
    normalizza_fase,
    riassumi_interventi,
)

CRS = "EPSG:32633"


@pytest.fixture
def sorgente_gpkg(tmp_path):
    """Sorgente sintetica: 3 velox puntuali con fase eterogenea."""
    gdf = gpd.GeoDataFrame(
        {
            "NOME": ["VLX-1", "VLX-2", "VLX-3"],
            "FATT": ["realizzato", "aprovato", None],
            "MUN": [1, 2, 3],
            "geometry": [Point(0, 0), Point(100, 0), Point(200, 0)],
        },
        crs=CRS,
    )
    percorso = tmp_path / "Velox.gpkg"
    gdf.to_file(percorso, driver="GPKG", layer="velox")
    return tmp_path


MAPPA_FASE = {
    "realizzato": "realizzato",
    "approvato": "pianificato",
    "aprovato": "pianificato",
    "PROGETTAZIONE IN CORSO": "in_corso",
}


class TestCaricaSorgente:
    def test_normalizzazione(self, sorgente_gpkg):
        cfg = {"file": "Velox.gpkg", "tipo": "velox",
               "campo_nome": "NOME", "campo_fase": "FATT",
               "campo_municipio": "MUN"}
        out = carica_sorgente(cfg, sorgente_gpkg, CRS)
        assert len(out) == 3
        assert list(out["id_intervento"]) == ["Velox:0000", "Velox:0001", "Velox:0002"]
        assert (out["tipo"] == "velox").all()
        assert out["nome"].iloc[0] == "VLX-1"
        assert out["fase_orig"].iloc[1] == "aprovato"
        assert out["municipio"].iloc[2] == 3

    def test_riproiezione(self, tmp_path):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(12.5, 41.9)]}, crs="EPSG:4326"
        )
        gdf.to_file(tmp_path / "A.gpkg", driver="GPKG")
        out = carica_sorgente({"file": "A.gpkg", "tipo": "x"}, tmp_path, CRS)
        assert str(out.crs) == CRS
        # Roma in UTM33N: X ~ 290km, Y ~ 4640km.
        assert 250_000 < out.geometry.iloc[0].x < 350_000


class TestNormalizzaFase:
    def test_mappa_case_insensitive_e_typo(self):
        orig = pd.Series(["realizzato", "APROVATO", "Progettazione In Corso",
                          "boh", None])
        fase = normalizza_fase(orig, MAPPA_FASE)
        assert list(fase) == ["realizzato", "pianificato", "in_corso",
                              "da_definire", "da_definire"]

    def test_mappa_invalida(self):
        with pytest.raises(ValueError):
            normalizza_fase(pd.Series(["x"]), {"x": "fase_inventata"})


class TestApplicaDate:
    def _gdf(self):
        return gpd.GeoDataFrame(
            {
                "id_intervento": ["A:0000", "A:0001"],
                "fase": ["da_definire", "da_definire"],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs=CRS,
        )

    def test_placeholder(self):
        out = applica_date(self._gdf(), "2025-01-01", None)
        assert (out["data_attivazione"] == pd.Timestamp("2025-01-01")).all()
        assert (out["data_stato"] == "placeholder").all()

    def test_override(self, tmp_path):
        csv = tmp_path / "date.csv"
        # Data futura ammessa (progetto non ancora attuato).
        csv.write_text(
            "id_intervento,data_attivazione,fase\n"
            "A:0001,2027-06-15,pianificato\n"
        )
        out = applica_date(self._gdf(), "2025-01-01", csv)
        assert out.loc[0, "data_stato"] == "placeholder"
        assert out.loc[1, "data_stato"] == "confermata"
        assert out.loc[1, "data_attivazione"] == pd.Timestamp("2027-06-15")
        assert out.loc[1, "fase"] == "pianificato"

    def test_override_id_sconosciuto_non_esplode(self, tmp_path):
        csv = tmp_path / "date.csv"
        csv.write_text("id_intervento,data_attivazione\nZZZ:9999,2025-05-01\n")
        out = applica_date(self._gdf(), "2025-01-01", csv)
        assert (out["data_stato"] == "placeholder").all()


class TestRaggioInfluenza:
    def test_puntuali_vs_areali(self):
        gdf = gpd.GeoDataFrame(
            {
                "tipo": ["velox", "isola_ambientale", "sconosciuto"],
                "geometry": [
                    Point(0, 0),
                    Polygon([(0, 0), (1, 0), (1, 1)]),
                    Point(5, 5),
                ],
            },
            crs=CRS,
        )
        raggi = {"velox": 500, "default_punti": 150}
        r = assegna_raggio_influenza(gdf, raggi)
        assert r.iloc[0] == 500.0     # puntuale con default per tipo
        assert r.iloc[1] == 0.0       # areale: conta l'impronta
        assert r.iloc[2] == 150.0     # puntuale senza default -> globale

    def test_riassunto(self):
        gdf = gpd.GeoDataFrame(
            {
                "tipo": ["velox", "velox"],
                "fase": ["realizzato", "da_definire"],
                "data_stato": ["placeholder", "confermata"],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs=CRS,
        )
        r = riassumi_interventi(gdf)
        assert r["n_interventi"] == 2
        assert r["per_tipo"] == {"velox": 2}
        assert r["date_confermate"] == 1
