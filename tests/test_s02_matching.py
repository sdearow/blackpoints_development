"""Test unitari per il matching spaziale incidenti <-> rete (Task 1.1a)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point

from src.s02_matching import (
    _endpoint_linea,
    _norm_topo,
    abbina_incidenti,
    abbinamento_geometrico_intersezioni,
    abbinamento_geometrico_segmenti,
    abbinamento_toponomastico,
    associa_semafori,
    costruisci_nodi,
    costruisci_segmenti,
    estrai_endpoint_archi,
    estrai_intersezioni,
    riassumi_intersezioni,
    riassumi_matching,
    riassumi_segmenti,
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


def test_estrai_intersezioni_filtra_falsi_incroci_stesso_toponimo():
    """Un nodo grado 3 con tutti gli archi dello stesso toponimo (es.
    confluenza carreggiate) viene filtrato come falso incrocio."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Roma", "Via Roma", "Via Roma"],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 100)]),
        ],
        crs="EPSG:32633",
    )
    gdf_int, _ = estrai_intersezioni(gdf, tolleranza_m=0.5, filtra_falsi_incroci=True)
    assert len(gdf_int) == 0

    gdf_int_no, _ = estrai_intersezioni(gdf, tolleranza_m=0.5, filtra_falsi_incroci=False)
    assert len(gdf_int_no) == 1


def test_estrai_intersezioni_non_filtra_grado_4_stesso_toponimo():
    """Nodi a grado >= 4 non vengono mai filtrati, anche con un solo toponimo."""
    gdf = _gdf_rete_a_croce()
    gdf["toponimo"] = ["Via Roma", "Via Roma", "Via Roma", "Via Roma"]
    gdf_int, _ = estrai_intersezioni(gdf, tolleranza_m=0.5, filtra_falsi_incroci=True)
    assert len(gdf_int) == 1


def test_costruisci_segmenti_attraversa_falso_incrocio():
    """Se un nodo grado-3 non e' nell'insieme intersezioni, la catena puo'
    attraversarlo quando c'e' un unico candidato con lo stesso toponimo
    (es. strada principale + spur senza nome)."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Roma", "Via Roma", None],
            "tgm": [1000.0, 1000.0, 500.0],
            "lunghezza_m": [100.0, 100.0, 80.0],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 80)]),
        ],
        crs="EPSG:32633",
    )
    gdf_int, df_archi_nodi = estrai_intersezioni(
        gdf, tolleranza_m=0.5, filtra_falsi_incroci=True
    )
    assert len(gdf_int) == 0
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi,
        soglia_var_tgm=0.30, lung_min=100, lung_max=2000,
        id_nodi_intersezione=set(),
    )
    lunghezze = sorted(gdf_seg["lunghezza_m"].tolist())
    assert lunghezze == pytest.approx([80.0, 200.0])


def test_costruisci_segmenti_non_attraversa_se_ambiguo():
    """Se al nodo falso incrocio ci sono 2 candidati con lo stesso toponimo,
    la catena si interrompe (ambiguita': non sappiamo quale e' la
    continuazione della strada principale)."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Roma", "Via Roma", "Via Roma"],
            "tgm": [1000.0, 1000.0, 500.0],
            "lunghezza_m": [100.0, 100.0, 80.0],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 80)]),
        ],
        crs="EPSG:32633",
    )
    gdf_int, df_archi_nodi = estrai_intersezioni(
        gdf, tolleranza_m=0.5, filtra_falsi_incroci=True
    )
    assert len(gdf_int) == 0
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi,
        soglia_var_tgm=0.30, lung_min=100, lung_max=2000,
        id_nodi_intersezione=set(),
    )
    assert len(gdf_seg) == 3


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


# ---------------------------------------------------------------------------
# _norm_topo
# ---------------------------------------------------------------------------


def test_norm_topo_normalizza_case_e_spazi():
    assert _norm_topo("Via dei Fori Imperiali") == "via dei fori imperiali"
    assert _norm_topo("VIA   DEI  FORI") == "via dei fori"
    assert _norm_topo("Via, dei-Fori") == "via dei fori"


def test_norm_topo_none_su_vuoto():
    assert _norm_topo(None) is None
    assert _norm_topo("") is None
    assert _norm_topo("   ") is None


# ---------------------------------------------------------------------------
# costruisci_segmenti
# ---------------------------------------------------------------------------


def _gdf_strada_dritta_3_archi() -> gpd.GeoDataFrame:
    """Tre archi collineari, stesso toponimo, stesso TGM (3x100 m)."""
    return gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Dritta", "Via Dritta", "Via Dritta"],
            "tgm": [1000.0, 1000.0, 1000.0],
            "lunghezza_m": [100.0, 100.0, 100.0],
            "classe_frc": [4, 4, 4],
            "limite_velocita": [50.0, 50.0, 50.0],
            "v_85": [55.0, 55.0, 55.0],
            "eccesso_v85": [5.0, 5.0, 5.0],
            "iqr_norm": [0.1, 0.1, 0.1],
            "pgtu_classifica": ["IQ", "IQ", "IQ"],
            "pgtu_tpl": [0.0, 0.0, 0.0],
            "grande_viabilita": [0.0, 0.0, 0.0],
            "linea_atac": [False, False, False],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (300, 0)]),
        ],
        crs="EPSG:32633",
    )


def test_costruisci_segmenti_strada_dritta_un_solo_segmento():
    gdf = _gdf_strada_dritta_3_archi()
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)

    gdf_seg, df_arco_seg = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    assert len(gdf_seg) == 1
    seg = gdf_seg.iloc[0]
    assert seg["n_archi"] == 3
    assert seg["lunghezza_m"] == pytest.approx(300.0)
    assert seg["isolato"] is False or bool(seg["isolato"]) is False
    assert sorted(seg["archi"]) == [1, 2, 3]
    # Mapping arco -> segmento copre tutti gli archi.
    assert len(df_arco_seg) == 3
    assert set(df_arco_seg["id_segmento"]) == {0}


def test_costruisci_segmenti_si_spezza_a_intersezione():
    """Rete a T: la strada principale (2 archi) viene tagliata
    dall'uscita laterale al nodo (100, 0), generando 2 segmenti
    + 1 segmento di un solo arco per la laterale."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Principale", "Via Principale", "Via Laterale"],
            "tgm": [1000.0, 1000.0, 500.0],
            "lunghezza_m": [100.0, 100.0, 100.0],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 100)]),
        ],
        crs="EPSG:32633",
    )
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    # 3 archi, 3 segmenti (l'intersezione spezza la principale e la laterale e' isolata).
    assert len(gdf_seg) == 3
    n_archi_per_seg = sorted(gdf_seg["n_archi"].tolist())
    assert n_archi_per_seg == [1, 1, 1]


def test_costruisci_segmenti_si_spezza_per_variazione_tgm():
    """Tre archi collineari ma il TGM passa da 1000 a 2000 (variazione 100%)
    sopra soglia 30%: il segmento si spezza tra l'arco 1 e l'arco 2."""
    gdf = _gdf_strada_dritta_3_archi()
    gdf["tgm"] = [1000.0, 2000.0, 2000.0]
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    # 2 segmenti: {1} e {2,3}.
    assert len(gdf_seg) == 2
    n_archi = sorted(gdf_seg["n_archi"].tolist())
    assert n_archi == [1, 2]


def test_costruisci_segmenti_marca_isolato_sotto_lung_min():
    """Un solo arco da 50 m: deve risultare 1 segmento marcato come isolato."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1], dtype="Int64"),
            "toponimo": ["Via Corta"],
            "tgm": [500.0],
            "lunghezza_m": [50.0],
        },
        geometry=[LineString([(0, 0), (50, 0)])],
        crs="EPSG:32633",
    )
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    assert len(gdf_seg) == 1
    assert bool(gdf_seg.iloc[0]["isolato"]) is True


def test_costruisci_segmenti_si_spezza_per_lunghezza_max():
    """5 archi da 600 m con lung_max=1000 m devono dare 3 segmenti
    (600+600 > 1000, quindi spezza ogni 1 arco se serve)."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3, 4, 5], dtype="Int64"),
            "toponimo": ["Via Lunga"] * 5,
            "tgm": [1000.0] * 5,
            "lunghezza_m": [600.0] * 5,
        },
        geometry=[
            LineString([(i * 600, 0), ((i + 1) * 600, 0)]) for i in range(5)
        ],
        crs="EPSG:32633",
    )
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=1000
    )
    # Greedy: [1] (600), poi 600+600>1000 ⇒ nuovo seg [2], poi [3], [4], [5].
    # Quindi ogni arco va da solo: 5 segmenti da 600 m.
    assert len(gdf_seg) == 5
    assert all(s == 600.0 for s in gdf_seg["lunghezza_m"])


def test_costruisci_segmenti_toponimo_diverso_separa():
    """Due archi consecutivi con toponimo diverso non vengono uniti."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2], dtype="Int64"),
            "toponimo": ["Via A", "Via B"],
            "tgm": [1000.0, 1000.0],
            "lunghezza_m": [200.0, 200.0],
        },
        geometry=[
            LineString([(0, 0), (200, 0)]),
            LineString([(200, 0), (400, 0)]),
        ],
        crs="EPSG:32633",
    )
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    assert len(gdf_seg) == 2


# ---------------------------------------------------------------------------
# riassumi_segmenti
# ---------------------------------------------------------------------------


def test_riassumi_segmenti_su_strada_dritta():
    gdf = _gdf_strada_dritta_3_archi()
    _, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(gdf, df_archi_nodi, df_nodi)
    r = riassumi_segmenti(gdf_seg)
    assert r["n_segmenti"] == 1
    assert r["n_isolati"] == 0
    assert r["lunghezza_totale_km"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# riassumi_intersezioni (continua)
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


# ---------------------------------------------------------------------------
# Matching incidenti (Task 1.2 + 1.3)
# ---------------------------------------------------------------------------


def _rete_a_T_completa():
    """Costruisce rete a T, intersezioni e segmenti per i test di matching."""
    gdf = gpd.GeoDataFrame(
        {
            "id_arco": pd.array([1, 2, 3], dtype="Int64"),
            "toponimo": ["Via Principale", "Via Principale", "Via Laterale"],
            "tgm": [1000.0, 1000.0, 500.0],
            "lunghezza_m": [100.0, 100.0, 100.0],
        },
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(100, 0), (100, 100)]),
        ],
        crs="EPSG:32633",
    )
    gdf_int, df_archi_nodi = estrai_intersezioni(gdf, tolleranza_m=0.5)
    gdf_int["is_semaforizzata"] = False
    gdf_int["n_semafori"] = 0
    gdf_int["id_impianti"] = [[] for _ in range(len(gdf_int))]
    df_ep = estrai_endpoint_archi(gdf)
    df_nodi, _ = costruisci_nodi(df_ep, tolleranza_m=0.5)
    gdf_seg, _ = costruisci_segmenti(
        gdf, df_archi_nodi, df_nodi, soglia_var_tgm=0.30, lung_min=100, lung_max=2000
    )
    return gdf_int, gdf_seg


def test_abbinamento_geometrico_intersezioni_entro_raggio():
    gdf_int, _ = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {"id_incidente": [1, 2, 3]},
        geometry=[
            Point(100, 0),   # sull'intersezione
            Point(100, 15),  # vicino (15 m)
            Point(100, 40),  # lontano (40 m)
        ],
        crs="EPSG:32633",
    )
    df = abbinamento_geometrico_intersezioni(gdf_inc, gdf_int, raggio_m=25.0)
    assert df.loc[1, "match_intersezione"]
    assert df.loc[2, "match_intersezione"]
    assert not df.loc[3, "match_intersezione"]


def test_abbinamento_geometrico_segmenti_soglia():
    _, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {"id_incidente": [1, 2]},
        geometry=[
            Point(50, 10),    # vicino all'arco 1 (10 m)
            Point(50, 200),   # lontano da tutti (>50 m)
        ],
        crs="EPSG:32633",
    )
    df = abbinamento_geometrico_segmenti(gdf_inc, gdf_seg, soglia_m=50.0)
    assert df.loc[1, "match_segmento"]
    assert not df.loc[2, "match_segmento"]


def test_abbina_incidenti_priorita_intersezione():
    """Un incidente sull'intersezione deve essere abbinato all'intersezione
    anche se ci sono segmenti vicinissimi."""
    gdf_int, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {
            "id_incidente": [1],
            "strada1": ["Via Principale"],
        },
        geometry=[Point(100, 0)],
        crs="EPSG:32633",
    )
    out = abbina_incidenti(
        gdf_inc, gdf_int, gdf_seg,
        raggio_intersezione_m=25.0,
        soglia_snap_geometrica_m=50.0,
        soglia_snap_toponomastica_m=100.0,
    )
    assert out.iloc[0]["match_type"] == "intersezione"


def test_abbina_incidenti_priorita_segmento():
    """Un incidente lontano dalle intersezioni ma vicino a un segmento
    deve essere abbinato al segmento."""
    gdf_int, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {
            "id_incidente": [1],
            "strada1": ["Via Principale"],
        },
        geometry=[Point(50, 5)],
        crs="EPSG:32633",
    )
    out = abbina_incidenti(
        gdf_inc, gdf_int, gdf_seg,
        raggio_intersezione_m=25.0,
        soglia_snap_geometrica_m=50.0,
        soglia_snap_toponomastica_m=100.0,
    )
    assert out.iloc[0]["match_type"] == "segmento"


def test_abbina_incidenti_fallback_toponomastico():
    """Un incidente fuori dalla soglia geometrica ma dentro la soglia
    toponomastica con un match fuzzy valido deve essere abbinato come
    segmento_toponimo."""
    gdf_int, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {
            "id_incidente": [1],
            "strada1": ["VIA PRINCIPALE"],  # stesso toponimo, case diversa
        },
        geometry=[Point(45, 55)],  # a 55 m dall'arco 1, fuori soglia geometrica
        crs="EPSG:32633",
    )
    out = abbina_incidenti(
        gdf_inc, gdf_int, gdf_seg,
        raggio_intersezione_m=25.0,
        soglia_snap_geometrica_m=50.0,
        soglia_snap_toponomastica_m=100.0,
    )
    assert out.iloc[0]["match_type"] == "segmento_toponimo"
    assert out.iloc[0]["score_topon"] >= 85


def test_abbina_incidenti_non_abbinato():
    """Un incidente molto lontano da tutto e senza toponimo compatibile
    deve restare non_abbinato."""
    gdf_int, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {
            "id_incidente": [1],
            "strada1": ["Via Inesistente"],
        },
        geometry=[Point(1000, 1000)],
        crs="EPSG:32633",
    )
    out = abbina_incidenti(
        gdf_inc, gdf_int, gdf_seg,
        raggio_intersezione_m=25.0,
        soglia_snap_geometrica_m=50.0,
        soglia_snap_toponomastica_m=100.0,
    )
    assert out.iloc[0]["match_type"] == "non_abbinato"


def test_riassumi_matching_conta_tipi():
    gdf_int, gdf_seg = _rete_a_T_completa()
    gdf_inc = gpd.GeoDataFrame(
        {
            "id_incidente": [1, 2, 3, 4],
            "strada1": ["Via Principale", "Via Principale", "Via Principale", "Inesistente"],
        },
        geometry=[
            Point(100, 0),     # intersezione
            Point(50, 5),      # segmento
            Point(45, 55),     # toponomastico
            Point(5000, 5000), # non abbinato
        ],
        crs="EPSG:32633",
    )
    out = abbina_incidenti(
        gdf_inc, gdf_int, gdf_seg,
        raggio_intersezione_m=25.0,
        soglia_snap_geometrica_m=50.0,
        soglia_snap_toponomastica_m=100.0,
    )
    r = riassumi_matching(out)
    assert r["n_incidenti"] == 4
    assert r["n_intersezione"] == 1
    assert r["n_segmento"] == 1
    assert r["n_segmento_toponimo"] == 1
    assert r["n_non_abbinato"] == 1
