"""Test unitari per il matching spaziale incidenti <-> rete (Task 1.1a)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point

from src.s02_matching import (
    _endpoint_linea,
    associa_semafori,
    costruisci_nodi,
    estrai_endpoint_archi,
    estrai_intersezioni,
    riassumi_intersezioni,
)


# ---------------------------------------------------------------------------
# _endpoint_linea
# ---------------------------------------------------------------------------


def test_endpoint_linea_su_linestring():
    geom = LineString([(0, 0), (5, 0), (10, 0)])
    start, end = _endpoint_linea(geom)
    assert start == (0.0, 0.0)
    assert end == (10.0, 0.0)


def test_endpoint_linea_su_multilinestring():
    geom = MultiLineString(
        [
            LineString([(0, 0), (5, 0)]),
            LineString([(5, 0), (10, 0)]),
        ]
    )
    start, end = _endpoint_linea(geom)
    assert start == (0.0, 0.0)
    assert end == (10.0, 0.0)


def test_endpoint_linea_none_su_vuoto_o_nullo():
    assert _endpoint_linea(None) is None
    assert _endpoint_linea(LineString()) is None


# ---------------------------------------------------------------------------
# estrai_endpoint_archi
# ---------------------------------------------------------------------------


def _gdf_rete_a_croce() -> gpd.GeoDataFrame:
    """Rete sintetica con 4 archi che convergono al punto (0, 0).

    Tutti gli archi partono da (0, 0) e vanno nelle 4 direzioni
    cardinali, creando un'intersezione a 4 bracci al centro.
    """
    return gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3, 4], dtype="Int64"),
            "toponimo": ["Via Nord", "Via Sud", "Via Est", "Via Ovest"],
            "tgm": [1000.0, 1000.0, 500.0, 500.0],
            "lunghezza_m": [100.0, 100.0, 100.0, 100.0],
        },
        geometry=[
            LineString([(0, 0), (0, 100)]),
            LineString([(0, 0), (0, -100)]),
            LineString([(0, 0), (100, 0)]),
            LineString([(0, 0), (-100, 0)]),
        ],
        crs="EPSG:32633",
    )


def test_estrai_endpoint_archi_due_righe_per_arco():
    gdf = _gdf_rete_a_croce()
    df = estrai_endpoint_archi(gdf)
    # 4 archi * 2 endpoint = 8 righe.
    assert len(df) == 8
    # Tutti gli archi hanno sia 'start' che 'end'.
    for id_arco in [1, 2, 3, 4]:
        sub = df.loc[df["id_arco"] == id_arco]
        assert set(sub["posizione"]) == {"start", "end"}


def test_estrai_endpoint_archi_richiede_id_arco():
    gdf = _gdf_rete_a_croce().drop(columns=["id_arco"])
    with pytest.raises(KeyError):
        estrai_endpoint_archi(gdf)


# ---------------------------------------------------------------------------
# costruisci_nodi
# ---------------------------------------------------------------------------


def test_costruisci_nodi_a_croce_trova_5_nodi_e_1_intersezione():
    gdf = _gdf_rete_a_croce()
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, df_archi_nodi = costruisci_nodi(df_ep, tolleranza_m=0.5)

    # 5 nodi distinti: centro (grado 4) + 4 estremi (grado 1).
    assert len(df_nodi) == 5
    assert int((df_nodi["n_archi"] == 4).sum()) == 1
    assert int((df_nodi["n_archi"] == 1).sum()) == 4

    # Mapping arco -> nodo_start / nodo_end presente per tutti.
    assert len(df_archi_nodi) == 4
    assert set(df_archi_nodi.columns) >= {"id_arco", "id_nodo_start", "id_nodo_end"}


def test_costruisci_nodi_tolleranza_unisce_endpoint_vicini():
    """Due archi con endpoint a 0.3 m di distanza vengono uniti con tolleranza 0.5 m."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2], dtype="Int64"),
            "toponimo": ["A", "B"],
        },
        geometry=[
            LineString([(0, 0), (10, 0)]),
            LineString([(10.3, 0), (20, 0)]),  # endpoint a 0.3 m
        ],
        crs="EPSG:32633",
    )
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)

    # 3 nodi: (0,0), (10±, 0) uniti, (20, 0).
    assert len(df_nodi) == 3
    n_grado_2 = int((df_nodi["n_archi"] == 2).sum())
    assert n_grado_2 == 1  # il nodo centrale ha grado 2


# ---------------------------------------------------------------------------
# estrai_intersezioni
# ---------------------------------------------------------------------------


def test_estrai_intersezioni_croce_restituisce_1_nodo_grado_4():
    gdf = _gdf_rete_a_croce()
    gdf_int, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)

    assert len(gdf_int) == 1
    assert gdf_int.iloc[0]["n_archi"] == 4
    # La geometria dell'intersezione e' a (0, 0).
    assert gdf_int.iloc[0].geometry.x == pytest.approx(0.0)
    assert gdf_int.iloc[0].geometry.y == pytest.approx(0.0)
    # Gli archi convergenti sono 1, 2, 3, 4.
    assert gdf_int.iloc[0]["archi"] == [1, 2, 3, 4]
    # I toponimi raccolti sono quelli distinti non nulli.
    assert gdf_int.iloc[0]["toponimi"] == ["Via Est", "Via Nord", "Via Ovest", "Via Sud"]

    # Mapping arco -> nodo presente per tutti.
    assert len(df_archi_nodi) == 4


def test_estrai_intersezioni_ignora_nodi_di_grado_2():
    """Una strada dritta composta da 3 archetti collineari non ha intersezioni."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Dritta", "Via Dritta", "Via Dritta"],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (300, 0)]),
        ],
        crs="EPSG:32633",
    )
    gdf_int, _ = estrai_intersezioni(gdf, tolleranza_m=0.5)
    # Nessuna intersezione: i nodi interni hanno grado 2.
    assert len(gdf_int) == 0


def test_estrai_intersezioni_rete_a_T():
    """Rete a T: una strada principale (2 archi) + un'uscita laterale."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Principale", "Via Principale", "Via Laterale"],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 100)]),  # uscita verso nord dal mezzo
        ],
        crs="EPSG:32633",
    )
    gdf_int, _ = estrai_intersezioni(gdf, tolleranza_m=0.5)
    # Una sola intersezione, a (100, 0), grado 3.
    assert len(gdf_int) == 1
    assert gdf_int.iloc[0]["n_archi"] == 3
    assert gdf_int.iloc[0].geometry.x == pytest.approx(100.0)
    assert gdf_int.iloc[0].geometry.y == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# associa_semafori
# ---------------------------------------------------------------------------


def _gdf_intersezioni_finto() -> gpd.GeoDataFrame:
    """Tre intersezioni in linea retta per i test di associazione semafori."""
    return gpd.GeoDataFrame(
        {
            "id_nodo": [10, 20, 30],
            "n_archi": [3, 4, 3],
            "archi": [[1, 2, 3], [4, 5, 6, 7], [8, 9, 10]],
            "toponimi": [["Via A"], ["Via A", "Via B"], ["Via B"]],
        },
        geometry=[Point(0, 0), Point(100, 0), Point(200, 0)],
        crs="EPSG:32633",
    )


def _gdf_semafori_finto_per_associazione() -> gpd.GeoDataFrame:
    """Quattro semafori: uno esatto, uno vicino, uno fuori raggio, uno pedonale."""
    return gpd.GeoDataFrame(
        {
            "id_impianto": ["S1", "S2", "S3", "S4"],
            "is_veicolare": pd.array([True, True, True, False], dtype="boolean"),
        },
        geometry=[
            Point(0, 0),       # sovrapposto all'intersezione 10
            Point(110, 5),     # vicino all'intersezione 20 (dist ~11 m)
            Point(200, 50),    # vicino all'intersezione 30 ma oltre soglia (50 m > 20)
            Point(0, 0),       # pedonale: deve essere ignorato
        ],
        crs="EPSG:32633",
    )


def test_associa_semafori_scelta_C_sempre_al_piu_vicino():
    gdf_int = _gdf_intersezioni_finto()
    gdf_sem = _gdf_semafori_finto_per_associazione()

    out = associa_semafori(gdf_int, gdf_sem, raggio_m=20.0)

    # Tutti e 3 i nodi hanno almeno un semaforo veicolare associato.
    # - nodo 10 <- S1 (dist 0)
    # - nodo 20 <- S2 (dist ~11)
    # - nodo 30 <- S3 (dist 50, oltre soglia ma comunque associato - scelta C)
    assert out["is_semaforizzata"].tolist() == [True, True, True]
    assert out["n_semafori"].tolist() == [1, 1, 1]

    # Il semaforo pedonale (S4) non e' stato associato.
    tutti_id = sum(out["id_impianti"].tolist(), [])
    assert "S4" not in tutti_id


def test_associa_semafori_senza_veicolari_nessuna_semaforizzazione():
    gdf_int = _gdf_intersezioni_finto()
    gdf_sem = gpd.GeoDataFrame(
        {
            "id_impianto": ["P1"],
            "is_veicolare": pd.array([False], dtype="boolean"),
        },
        geometry=[Point(0, 0)],
        crs="EPSG:32633",
    )
    out = associa_semafori(gdf_int, gdf_sem, raggio_m=20.0)
    assert out["is_semaforizzata"].tolist() == [False, False, False]
    assert out["n_semafori"].tolist() == [0, 0, 0]


def test_associa_semafori_riproietta_automaticamente():
    gdf_int = _gdf_intersezioni_finto()
    gdf_sem = _gdf_semafori_finto_per_associazione().to_crs("EPSG:4326")
    out = associa_semafori(gdf_int, gdf_sem, raggio_m=20.0)
    # Almeno uno dei nodi e' semaforizzato (il S1 sovrapposto a (0, 0)).
    assert bool(out.iloc[0]["is_semaforizzata"]) is True


# ---------------------------------------------------------------------------
# riassumi_intersezioni
# ---------------------------------------------------------------------------


def test_riassumi_intersezioni_conta_grado_e_semafori():
    gdf_int = _gdf_intersezioni_finto()
    gdf_sem = _gdf_semafori_finto_per_associazione()
    gdf_int = associa_semafori(gdf_int, gdf_sem, raggio_m=20.0)
    r = riassumi_intersezioni(gdf_int)
    assert r["n_intersezioni"] == 3
    assert r["n_semaforizzate"] == 3
    assert r["n_semafori_associati"] == 3
    assert r["n_per_grado"][3] == 2
    assert r["n_per_grado"][4] == 1
