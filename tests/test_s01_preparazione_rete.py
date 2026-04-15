"""Test unitari per la preparazione della rete TomTom (Task 0.2)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point

from src.s01_preparazione_rete import (
    _boolifica_si_no,
    _pulisci_categoria,
    calcola_derivate,
    joina_pgtu,
    pulisci_geometrie,
    riassumi,
    riassumi_semafori,
    standardizza_colonne,
    standardizza_semafori,
    valida_rete,
    valida_semafori,
)


def _gdf_finto(n: int = 3) -> gpd.GeoDataFrame:
    """Costruisce un GeoDataFrame minimale con lo schema TomTom grezzo."""
    geoms = [
        MultiLineString([LineString([(0, 0), (1, 0)])]),
        MultiLineString([LineString([(0, 0), (0, 1)])]),
        MultiLineString([LineString([(1, 1), (2, 2)])]),
    ][:n]
    dati = {
        "Id": [1.0, 2.0, 3.0][:n],
        "FRC": [5.0, 6.0, 2.0][:n],
        "SpeedLimit": [50.0, 30.0, 90.0][:n],
        "StreetName": ["Via Tiberina", "Via Appia", "GRA"][:n],
        "VEIC_DAY_T": [5000.0, 1000.0, 40000.0][:n],
        "VEIC_0809_": [200.0, 50.0, 3000.0][:n],
        "VEIC_1819_": [300.0, 70.0, 3200.0][:n],
        "VEIC_08091": [500.0, 120.0, 6200.0][:n],
        "PCT_PUNTA_": [0.1, 0.12, 0.15][:n],
        "ATAC": ["Si", "No", "No"][:n],
        "BS_AvgTt": [1.0, 2.0, 3.0][:n],
        "BS_MedTt": [1.0, 2.0, 3.0][:n],
        "BS_ratio": [1.0, 1.1, 1.0][:n],
        "BS_AvgSp": [40.0, 25.0, 100.0][:n],
        "BS_HvgSp": [38.0, 24.0, 98.0][:n],
        "BS_MedSp": [41.0, 26.0, 101.0][:n],
        "BS_SdSp": [5.0, 4.0, 10.0][:n],
        "BS_P5sp": [30.0, 20.0, 80.0][:n],
        "BS_P10sp": [32.0, 21.0, 82.0][:n],
        "BS_P15sp": [34.0, 22.0, 84.0][:n],
        "BS_P20sp": [35.0, 23.0, 86.0][:n],
        "BS_P25sp": [36.0, 24.0, 90.0][:n],
        "BS_P30sp": [37.0, 24.5, 92.0][:n],
        "BS_P35sp": [38.0, 25.0, 94.0][:n],
        "BS_P40sp": [39.0, 25.5, 96.0][:n],
        "BS_P45sp": [40.0, 26.0, 98.0][:n],
        "BS_P50sp": [41.0, 26.5, 100.0][:n],
        "BS_P55sp": [42.0, 27.0, 102.0][:n],
        "BS_P60sp": [43.0, 27.5, 104.0][:n],
        "BS_P65sp": [44.0, 28.0, 106.0][:n],
        "BS_P70sp": [45.0, 28.5, 108.0][:n],
        "BS_P75sp": [46.0, 29.0, 110.0][:n],
        "BS_P80sp": [47.0, 29.5, 112.0][:n],
        "BS_P85sp": [55.0, 30.0, 115.0][:n],
        "BS_P90sp": [58.0, 32.0, 118.0][:n],
        "BS_P95sp": [62.0, 35.0, 122.0][:n],
        "Shape_Leng": [100.0, 250.0, 1500.0][:n],
    }
    return gpd.GeoDataFrame(dati, geometry=geoms, crs="EPSG:3004")


# ---------------------------------------------------------------------------
# _boolifica_si_no
# ---------------------------------------------------------------------------


def test_boolifica_si_no_mappa_casi_comuni():
    serie = pd.Series(["Si", "no", "SI", "No", "  si ", None, "", "???"])
    risultato = _boolifica_si_no(serie)
    assert risultato.tolist()[:5] == [True, False, True, False, True]
    # None / "" / valori sconosciuti -> pd.NA
    assert pd.isna(risultato.iloc[5])
    assert pd.isna(risultato.iloc[6])
    assert pd.isna(risultato.iloc[7])


# ---------------------------------------------------------------------------
# _pulisci_categoria
# ---------------------------------------------------------------------------


def test_pulisci_categoria_converte_trattino_in_nan():
    serie = pd.Series(["Q", "-", "IQ", "", "S", "None"])
    risultato = _pulisci_categoria(serie)
    assert risultato.iloc[0] == "Q"
    assert pd.isna(risultato.iloc[1])
    assert risultato.iloc[2] == "IQ"
    assert pd.isna(risultato.iloc[3])
    assert risultato.iloc[4] == "S"
    assert pd.isna(risultato.iloc[5])
    assert str(risultato.dtype) == "category"


# ---------------------------------------------------------------------------
# standardizza_colonne
# ---------------------------------------------------------------------------


def test_standardizza_colonne_rinomina_e_casta():
    gdf = _gdf_finto()
    # Aggiungo manualmente le colonne da ignorare per verificare che vengano droppate.
    gdf = gdf.assign(GV2019=["Si", "No", "Si"], CF_PGTU201=["Q", "-", "S"])
    out = standardizza_colonne(gdf)

    # Rinomina applicata sulle colonne attese.
    for col in ("id_arco", "classe_frc", "limite_velocita", "toponimo",
                "tgm", "v_85", "v_p25", "v_p75", "lunghezza_m", "linea_atac"):
        assert col in out.columns, f"manca {col}"

    # Le colonne ignorate sono state droppate dallo standardizzatore.
    assert "GV2019" not in out.columns
    assert "CF_PGTU201" not in out.columns
    assert "grande_viabilita" not in out.columns  # verra' aggiunta da joina_pgtu
    assert "pgtu_2019" not in out.columns
    assert "pgtu_classifica" not in out.columns  # idem

    # Tipi.
    assert out["id_arco"].dtype.name == "Int64"
    assert out["classe_frc"].dtype.name == "Int64"
    assert out["linea_atac"].dtype.name == "boolean"

    # Valore booleano del flag nativo ATAC.
    assert out["linea_atac"].tolist() == [True, False, False]


# ---------------------------------------------------------------------------
# calcola_derivate
# ---------------------------------------------------------------------------


def test_calcola_derivate_aggiunge_log_e_iqr():
    gdf = standardizza_colonne(_gdf_finto())
    out = calcola_derivate(gdf)

    for col in ("log_tgm", "log_lunghezza", "iqr_velocita", "iqr_norm",
                "ratio_v85_limite", "eccesso_v85"):
        assert col in out.columns, f"manca {col}"

    # log_tgm: log(5000) ~ 8.52.
    assert out["log_tgm"].iloc[0] == pytest.approx(np.log(5000), rel=1e-6)

    # iqr_velocita: P75 - P25 = 46 - 36 = 10.
    assert out["iqr_velocita"].iloc[0] == pytest.approx(10.0)

    # iqr_norm: 10 / 50 = 0.2.
    assert out["iqr_norm"].iloc[0] == pytest.approx(0.2)

    # ratio_v85_limite: 55 / 50 = 1.1.
    assert out["ratio_v85_limite"].iloc[0] == pytest.approx(1.1)

    # eccesso_v85: max(55-50, 0) = 5; riga 1: max(30-30, 0) = 0.
    assert out["eccesso_v85"].iloc[0] == pytest.approx(5.0)
    assert out["eccesso_v85"].iloc[1] == pytest.approx(0.0)


def test_calcola_derivate_tgm_zero_non_fa_crashare():
    gdf = standardizza_colonne(_gdf_finto())
    gdf.loc[0, "tgm"] = 0.0
    out = calcola_derivate(gdf)
    # log(max(0, 1)) = 0.
    assert out["log_tgm"].iloc[0] == pytest.approx(0.0)
    assert np.isfinite(out["log_tgm"].iloc[0])


# ---------------------------------------------------------------------------
# pulisci_geometrie
# ---------------------------------------------------------------------------


def test_pulisci_geometrie_scarta_nulle_e_vuote():
    geoms = [
        MultiLineString([LineString([(0, 0), (1, 0)])]),
        None,
        MultiLineString([]),
        MultiLineString([LineString([(0, 0), (0, 1)])]),
    ]
    gdf = gpd.GeoDataFrame({"Id": [1, 2, 3, 4]}, geometry=geoms, crs="EPSG:3004")
    out = pulisci_geometrie(gdf)
    assert len(out) == 2
    assert out["Id"].tolist() == [1, 4]


# ---------------------------------------------------------------------------
# valida_rete
# ---------------------------------------------------------------------------


def test_valida_rete_rileva_duplicati_id():
    gdf = _gdf_finto()
    gdf.loc[2, "Id"] = 1.0  # duplica il primo Id
    diagnosi = valida_rete(gdf)
    assert diagnosi["n_totali"] == 3
    assert diagnosi["n_duplicati_id"] == 1
    assert diagnosi["n_geom_nulle"] == 0


# ---------------------------------------------------------------------------
# riassumi
# ---------------------------------------------------------------------------


def test_riassumi_ritorna_conteggi_principali():
    gdf = calcola_derivate(standardizza_colonne(_gdf_finto()))
    riassunto = riassumi(gdf)
    assert riassunto["n_archi"] == 3
    assert riassunto["lunghezza_km_totale"] == pytest.approx((100 + 250 + 1500) / 1000.0)
    assert riassunto["n_linea_atac"] == 1
    # Senza join PGTU 'grande_viabilita' non e' presente.
    assert riassunto["n_grande_viabilita"] == 0
    assert "n_per_frc" in riassunto


# ---------------------------------------------------------------------------
# joina_pgtu
# ---------------------------------------------------------------------------


def _gdf_rete_metrico() -> gpd.GeoDataFrame:
    """Rete TomTom finta gia' standardizzata, in EPSG:32633 (metri)."""
    # Tre archi: uno sovrapposto al PGTU 'S', uno a 5m di distanza da un PGTU 'Q',
    # uno lontano 500m da tutto.
    geoms = [
        LineString([(0, 0), (100, 0)]),      # match S
        LineString([(0, 105), (100, 105)]),  # match Q (midpoint a (50, 105))
        LineString([(0, 600), (100, 600)]),  # nessun match
    ]
    gdf = gpd.GeoDataFrame(
        {"id_arco": pd.array([1, 2, 3], dtype="Int64")},
        geometry=geoms,
        crs="EPSG:32633",
    )
    return gdf


def _gdf_pgtu_metrico() -> gpd.GeoDataFrame:
    """Grafo PGTU finto in EPSG:32633 con classifica e grande_viabilita."""
    geoms = [
        LineString([(0, 0), (100, 0)]),     # arco S, sovrapposto al TomTom 1
        LineString([(0, 100), (100, 100)]),  # arco Q, a ~5m dal TomTom 2 (y=105)
    ]
    gdf = gpd.GeoDataFrame(
        {
            "classifica": pd.Categorical(["S", "Q"], categories=["S", "IQ", "IZ", "Q"]),
            "grande_viabilita": pd.array([True, False], dtype="boolean"),
            "tpl": pd.array([True, True], dtype="boolean"),
            "nome": ["Via Grande", "Via Quartiere"],
        },
        geometry=geoms,
        crs="EPSG:32633",
    )
    return gdf


def test_joina_pgtu_associa_classifica_entro_raggio():
    gdf_rete = _gdf_rete_metrico()
    gdf_pgtu = _gdf_pgtu_metrico()

    out = joina_pgtu(gdf_rete, gdf_pgtu, raggio_m=15.0)

    # Arco 1: sovrapposto a S.
    assert out.iloc[0]["pgtu_classifica"] == "S"
    assert bool(out.iloc[0]["grande_viabilita"]) is True
    assert out.iloc[0]["pgtu_distanza_m"] == pytest.approx(0.0, abs=1e-6)

    # Arco 2: midpoint a (50, 105), arco Q a y=100 -> distanza 5m.
    assert out.iloc[1]["pgtu_classifica"] == "Q"
    assert bool(out.iloc[1]["grande_viabilita"]) is False
    assert out.iloc[1]["pgtu_distanza_m"] == pytest.approx(5.0, abs=1e-6)

    # Arco 3: fuori raggio -> NaN.
    assert pd.isna(out.iloc[2]["pgtu_classifica"])
    assert pd.isna(out.iloc[2]["grande_viabilita"])


def test_joina_pgtu_raggio_stretto_non_matcha():
    gdf_rete = _gdf_rete_metrico()
    gdf_pgtu = _gdf_pgtu_metrico()

    # Raggio 2m: l'arco 2 (a 5m) non matcha, il 3 (lontano) nemmeno.
    out = joina_pgtu(gdf_rete, gdf_pgtu, raggio_m=2.0)

    assert out.iloc[0]["pgtu_classifica"] == "S"
    assert pd.isna(out.iloc[1]["pgtu_classifica"])
    assert pd.isna(out.iloc[2]["pgtu_classifica"])


def test_joina_pgtu_riproietta_automaticamente():
    gdf_rete = _gdf_rete_metrico()
    gdf_pgtu = _gdf_pgtu_metrico().to_crs("EPSG:4326")  # PGTU in altro CRS

    out = joina_pgtu(gdf_rete, gdf_pgtu, raggio_m=15.0)

    # Il join riproietta internamente: l'arco 1 resta matchato a S.
    assert out.iloc[0]["pgtu_classifica"] == "S"


# ---------------------------------------------------------------------------
# Semafori
# ---------------------------------------------------------------------------


def _gdf_semafori_finto() -> gpd.GeoDataFrame:
    """Dataset semafori finto con lo schema del file del Comune."""
    punti = [Point(12.5, 41.9), Point(12.51, 41.91), Point(12.52, 41.92),
             Point(12.53, 41.93)]
    return gpd.GeoDataFrame(
        {
            "COD_IMP": ["00001", "00002", "00003", "00004"],
            "TIPO": ["V", "V", "P", "V"],
            "VIA_1": ["Via Cassia", "VIA APPIA", "Via Tiberina", "V.le Trastevere"],
            "CIV": [None, None, "10", None],
            "VIA_2": ["Via di Grottarossa", "Via Appia Pignatelli", None, "Via Marmorata"],
            "VIA_3": [None, "Via Ardeatina", None, None],
            "CIRC": ["XV", "VII", "III", "I"],
            "Long": [12.5, 12.51, 12.52, 12.53],
            "Lat": [41.9, 41.91, 41.92, 41.93],
        },
        geometry=punti,
        crs="EPSG:4326",
    )


def test_standardizza_semafori_rinomina_e_deriva_flag():
    gdf = _gdf_semafori_finto()
    out = standardizza_semafori(gdf)

    # Colonne rinominate.
    for col in ("id_impianto", "tipo", "via_1", "via_2", "via_3",
                "civico", "municipio_romano", "is_veicolare", "n_bracci"):
        assert col in out.columns, f"manca {col}"

    # Long/Lat droppate (ridondanti con la geometria).
    assert "Long" not in out.columns
    assert "Lat" not in out.columns

    # Tipi.
    assert str(out["tipo"].dtype) == "category"
    assert out["is_veicolare"].dtype.name == "boolean"
    assert out["n_bracci"].dtype.name == "Int64"

    # Flag veicolare: V -> True, P -> False.
    assert out["is_veicolare"].tolist() == [True, True, False, True]

    # n_bracci: 2, 3, 1, 2.
    assert out["n_bracci"].tolist() == [2, 3, 1, 2]


def test_standardizza_semafori_normalizza_toponimi():
    gdf = _gdf_semafori_finto()
    out = standardizza_semafori(gdf)
    # 'VIA APPIA' -> 'Via Appia', 'V.le Trastevere' -> 'Viale Trastevere'.
    assert out.loc[1, "via_1"] == "Via Appia"
    assert out.loc[3, "via_1"] == "Viale Trastevere"
    # 'Via Cassia' (gia' corretto) resta tale.
    assert out.loc[0, "via_1"] == "Via Cassia"


def test_valida_semafori_rileva_duplicati():
    gdf = _gdf_semafori_finto()
    gdf.loc[2, "COD_IMP"] = "00001"
    diagnosi = valida_semafori(gdf)
    assert diagnosi["n_totali"] == 4
    assert diagnosi["n_duplicati_id"] == 1
    assert diagnosi["n_geom_nulle"] == 0


def test_riassumi_semafori_conta_per_tipo_e_bracci():
    gdf = standardizza_semafori(_gdf_semafori_finto())
    riassunto = riassumi_semafori(gdf)
    assert riassunto["n_totali"] == 4
    assert riassunto["n_veicolari"] == 3
    assert riassunto["n_per_tipo"]["V"] == 3
    assert riassunto["n_per_tipo"]["P"] == 1
    # n_bracci: tre record con 2, uno con 3, uno con 1 -> {2:2, 3:1, 1:1}
    assert riassunto["n_per_bracci"][2] == 2
    assert riassunto["n_per_bracci"][3] == 1
    assert riassunto["n_per_bracci"][1] == 1
