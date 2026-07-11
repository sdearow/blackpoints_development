"""Test unitari per il calcolo dell'Indice Composito di Priorita' (Fase 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.s05_indice_composito import (
    assembla_priorita,
    calcola_componente_A,
    calcola_componente_B,
    calcola_componente_C,
    calcola_componente_D_intersezioni,
    calcola_componente_D_segmenti,
    calcola_icp,
    classifica_fasce,
    classifica_matrice,
    normalizza_robusta,
    riassumi_priorita,
)

PESI = {"eccesso_eb": 0.40, "severita": 0.25, "vulnerabilita": 0.20, "rischio_velocita": 0.15}
SOGLIE = [20.0, 40.0, 60.0, 80.0]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _df_segmenti_finto(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id_segmento": range(n),
            "excess_EPDO_i": rng.normal(5, 3, n),
            "n_incidenti": rng.poisson(5, n).astype(float),
            "n_mortali": rng.binomial(1, 0.01, n).astype(float),
            "n_feriti": rng.binomial(2, 0.05, n).astype(float),
            "n_pedoni": rng.binomial(2, 0.1, n).astype(float),
            "v85_medio": rng.uniform(40, 80, n),
            "limite_velocita_medio": [50.0] * n,
            "iqr_velocita_medio": rng.uniform(2.0, 15.0, n),
            "iqr_norm_medio": rng.uniform(0.05, 0.3, n),
        }
    )


def _df_intersezioni_finto(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id_nodo": range(n),
            "excess_EPDO_i": rng.normal(3, 2, n),
            "n_incidenti": rng.poisson(8, n).astype(float),
            "n_mortali": rng.binomial(1, 0.01, n).astype(float),
            "n_feriti": rng.binomial(2, 0.05, n).astype(float),
            "n_pedoni": rng.binomial(3, 0.15, n).astype(float),
        }
    )


def _gdf_rete_finto(n_archi: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id_arco": range(1, n_archi + 1),
            "v_85": rng.uniform(40, 80, n_archi),
            "limite_velocita": [50.0] * n_archi,
            "iqr_norm": rng.uniform(0.05, 0.3, n_archi),
            "tgm": rng.uniform(500, 30000, n_archi),
        }
    )


def _gdf_intersezioni_finto(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for i in range(n):
        archi_ids = rng.integers(1, 201, size=3)
        rows.append({"id_nodo": i, "archi": "|".join(str(x) for x in archi_ids)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# calcola_componente_A
# ---------------------------------------------------------------------------


def test_componente_A_usa_excess_epdo():
    df = pd.DataFrame({"excess_EPDO_i": [1.0, 5.0, -2.0]})
    a = calcola_componente_A(df)
    np.testing.assert_allclose(a.values, [1.0, 5.0, -2.0])


def test_componente_A_nan_diventa_zero():
    df = pd.DataFrame({"excess_EPDO_i": [np.nan, 3.0]})
    a = calcola_componente_A(df)
    assert a.iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# calcola_componente_B
# ---------------------------------------------------------------------------


def test_componente_B_formula():
    # n_incidenti >= n_min -> credibilita' 1: B = (mortali+feriti)/n.
    df = pd.DataFrame(
        {"n_incidenti": [10.0], "n_mortali": [1.0], "n_feriti": [2.0]}
    )
    b = calcola_componente_B(df)
    assert b.iloc[0] == pytest.approx(3.0 / 10.0)


def test_componente_B_credibilita_smorza_pochi_incidenti():
    # 2 incidenti su n_min=5 -> credibilita' 2/5: B = (2/2) * (2/5).
    df = pd.DataFrame(
        {"n_incidenti": [2.0], "n_mortali": [1.0], "n_feriti": [1.0]}
    )
    b = calcola_componente_B(df, n_min=5)
    assert b.iloc[0] == pytest.approx(0.4)


def test_componente_B_zero_incidenti():
    df = pd.DataFrame(
        {"n_incidenti": [0.0], "n_mortali": [0.0], "n_feriti": [0.0]}
    )
    b = calcola_componente_B(df)
    assert b.iloc[0] == pytest.approx(0.0)


def test_componente_B_tra_0_e_1():
    df = _df_segmenti_finto(200)
    b = calcola_componente_B(df)
    assert (b >= 0).all()
    assert (b <= 1).all()


# ---------------------------------------------------------------------------
# calcola_componente_C
# ---------------------------------------------------------------------------


def test_componente_C_formula():
    df = pd.DataFrame({"n_incidenti": [10.0], "n_pedoni": [3.0]})
    c = calcola_componente_C(df)
    assert c.iloc[0] == pytest.approx(0.3)


def test_componente_C_zero_incidenti():
    df = pd.DataFrame({"n_incidenti": [0.0], "n_pedoni": [0.0]})
    c = calcola_componente_C(df)
    assert c.iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# calcola_componente_D_segmenti
# ---------------------------------------------------------------------------


def test_componente_D_segmenti_usa_iqr_velocita():
    # D = IQR delle velocita' in km/h (V75-V25), indipendente dai limiti
    # (non sempre aggiornati nella base dati).
    df = pd.DataFrame({"iqr_velocita_medio": [7.5], "iqr_norm_medio": [0.1]})
    d = calcola_componente_D_segmenti(df)
    assert d.iloc[0] == pytest.approx(7.5)


def test_componente_D_segmenti_fallback_iqr_norm():
    # Retro-compatibilita': senza iqr_velocita_medio usa iqr_norm_medio.
    df = pd.DataFrame({"iqr_norm_medio": [0.2]})
    d = calcola_componente_D_segmenti(df)
    assert d.iloc[0] == pytest.approx(0.2)


def test_componente_D_segmenti_non_negativa():
    df = _df_segmenti_finto(100)
    d = calcola_componente_D_segmenti(df)
    assert (d >= 0).all()


# ---------------------------------------------------------------------------
# calcola_componente_D_intersezioni
# ---------------------------------------------------------------------------


def test_componente_D_intersezioni_restituisce_serie():
    df_int = _df_intersezioni_finto(20)
    gdf_rete = _gdf_rete_finto(200)
    gdf_int_geo = _gdf_intersezioni_finto(20)
    d = calcola_componente_D_intersezioni(df_int, gdf_rete, gdf_int_geo)
    assert isinstance(d, pd.Series)
    assert len(d) == 20


def test_componente_D_intersezioni_non_negativa():
    df_int = _df_intersezioni_finto(30)
    gdf_rete = _gdf_rete_finto(200)
    gdf_int_geo = _gdf_intersezioni_finto(30)
    d = calcola_componente_D_intersezioni(df_int, gdf_rete, gdf_int_geo)
    assert (d >= 0).all()


def test_componente_D_intersezioni_senza_archi_e_zero():
    df_int = pd.DataFrame({"id_nodo": [99]})
    gdf_rete = _gdf_rete_finto(10)
    gdf_int_geo = pd.DataFrame({"id_nodo": [99], "archi": [""]})
    d = calcola_componente_D_intersezioni(df_int, gdf_rete, gdf_int_geo)
    assert d.iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# normalizza_robusta
# ---------------------------------------------------------------------------


def test_normalizza_robusta_range_0_100():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 20)
    n = normalizza_robusta(s)
    assert n.min() >= 0.0
    assert n.max() <= 100.0


def test_normalizza_robusta_costante_produce_zero():
    s = pd.Series([5.0] * 50)
    n = normalizza_robusta(s)
    assert (n == 0.0).all()


def test_normalizza_robusta_valori_estremi_clippati():
    s = pd.Series(list(range(100)))
    n = normalizza_robusta(s, p_min=10.0, p_max=90.0)
    assert n.min() == pytest.approx(0.0)
    assert n.max() == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# calcola_icp
# ---------------------------------------------------------------------------


def test_calcola_icp_formula():
    df = pd.DataFrame(
        {"A_norm": [50.0], "B_norm": [40.0], "C_norm": [30.0], "D_norm": [20.0]}
    )
    icp = calcola_icp(df, PESI)
    atteso = 0.40 * 50 + 0.25 * 40 + 0.20 * 30 + 0.15 * 20
    assert icp.iloc[0] == pytest.approx(atteso)


def test_calcola_icp_pesi_all_zero_produce_zero():
    df = pd.DataFrame(
        {"A_norm": [50.0], "B_norm": [40.0], "C_norm": [30.0], "D_norm": [20.0]}
    )
    pesi_zero = {"eccesso_eb": 0.0, "severita": 0.0, "vulnerabilita": 0.0, "rischio_velocita": 0.0}
    icp = calcola_icp(df, pesi_zero)
    assert icp.iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# classifica_fasce
# ---------------------------------------------------------------------------


def test_classifica_fasce_cinque_categorie():
    icp = pd.Series(np.linspace(0, 100, 500))
    fasce = classifica_fasce(icp, SOGLIE)
    cats = set(fasce.unique())
    assert cats == {"monitoraggio", "bassa", "media", "alta", "altissima"}


def test_classifica_fasce_proporzioni_approssimate():
    icp = pd.Series(np.linspace(0, 100, 1000))
    fasce = classifica_fasce(icp, SOGLIE)
    # Con soglie ai percentili [20,40,60,80] ci si aspetta ~20% per fascia.
    for cat in ["monitoraggio", "bassa", "media", "alta", "altissima"]:
        pct = (fasce == cat).mean()
        assert 0.15 < pct < 0.25, f"fascia {cat}: {pct:.2%}"


# ---------------------------------------------------------------------------
# classifica_matrice
# ---------------------------------------------------------------------------


def test_classifica_matrice_quattro_quadranti():
    df = _df_segmenti_finto(200)
    df["A"] = calcola_componente_A(df)
    df["B"] = calcola_componente_B(df)
    quadranti = classifica_matrice(df)
    cats = set(quadranti.unique())
    assert "Q1_intervento_urgente" in cats or "Q2_intervento_programmato" in cats


def test_classifica_matrice_tutti_i_quadranti_presenti():
    # Le soglie sono al 75° percentile (sui siti con incidenti): la coda
    # "alta" deve essere < 25% per superare la soglia. 400 siti:
    # 225 Q4 (basso/basso), 75 Q3 (basso/alto), 75 Q2 (alto/basso),
    # 25 Q1 (alto/alto).
    df = pd.DataFrame(
        {
            "A": [1.0] * 225 + [1.0] * 75 + [10.0] * 75 + [10.0] * 25,
            "B": [0.1] * 225 + [0.9] * 75 + [0.1] * 75 + [0.9] * 25,
            "n_incidenti": [1.0] * 400,
        }
    )
    quadranti = classifica_matrice(df)
    assert set(quadranti.unique()) == {
        "Q1_intervento_urgente",
        "Q2_intervento_programmato",
        "Q3_indagine_approfondita",
        "Q4_monitoraggio",
    }


# ---------------------------------------------------------------------------
# assembla_priorita
# ---------------------------------------------------------------------------


def test_assembla_priorita_colonne_obbligatorie():
    df = _df_segmenti_finto(100)
    df["D"] = calcola_componente_D_segmenti(df)
    out = assembla_priorita(df, "segmento", PESI, SOGLIE, p_min=1.0, p_max=99.0)
    for col in ("A", "B", "C", "D", "A_norm", "B_norm", "C_norm", "D_norm",
                "ICP", "fascia_priorita", "quadrante_rischio", "tipo_sito"):
        assert col in out.columns, f"colonna mancante: {col}"


def test_assembla_priorita_icp_in_range():
    df = _df_segmenti_finto(100)
    df["D"] = calcola_componente_D_segmenti(df)
    out = assembla_priorita(df, "segmento", PESI, SOGLIE, p_min=1.0, p_max=99.0)
    assert out["ICP"].between(0, 100).all()


def test_assembla_priorita_tipo_sito_corretto():
    df = _df_segmenti_finto(50)
    df["D"] = calcola_componente_D_segmenti(df)
    out = assembla_priorita(df, "intersezione", PESI, SOGLIE, p_min=1.0, p_max=99.0)
    assert (out["tipo_sito"] == "intersezione").all()


# ---------------------------------------------------------------------------
# riassumi_priorita
# ---------------------------------------------------------------------------


def test_riassumi_priorita_struttura():
    df = _df_segmenti_finto(100)
    df["D"] = calcola_componente_D_segmenti(df)
    out = assembla_priorita(df, "segmento", PESI, SOGLIE, p_min=1.0, p_max=99.0)
    r = riassumi_priorita(out)
    assert "n_siti" in r
    assert "ICP_mediana" in r
    assert "ICP_p90" in r
    assert "ICP_max" in r
    assert "fasce" in r
    assert "quadranti" in r


def test_riassumi_priorita_n_siti_corretto():
    df = _df_segmenti_finto(77)
    df["D"] = calcola_componente_D_segmenti(df)
    out = assembla_priorita(df, "segmento", PESI, SOGLIE, p_min=1.0, p_max=99.0)
    r = riassumi_priorita(out)
    assert r["n_siti"] == 77


def test_classifica_fasce_zero_inflated_non_collassa():
    """Distribuzione degenere (80% della massa su un valore, come l'ICP
    dei segmenti di Roma): le soglie percentili collassano e senza
    fallback restano solo 2 fasce. Il fallback deve produrne 5."""
    rng = np.random.default_rng(42)
    massa = np.full(800, 24.843)                 # eccesso nullo
    positivi = 24.843 + rng.uniform(0.1, 75.0, 200)
    icp = pd.Series(np.concatenate([massa, positivi]))
    fasce = classifica_fasce(icp, SOGLIE)
    assert set(fasce.unique()) == {"monitoraggio", "bassa", "media",
                                   "alta", "altissima"}
    # Tutta la massa degenere sta in monitoraggio.
    assert (fasce[icp <= 24.843] == "monitoraggio").all()
    # I positivi si ripartiscono ~25% per fascia.
    sopra = fasce[icp > 24.843].value_counts(normalize=True)
    for f in ("bassa", "media", "alta", "altissima"):
        assert 0.15 < sopra[f] < 0.35


def test_classifica_fasce_tutta_massa_degenere():
    icp = pd.Series(np.zeros(100))
    fasce = classifica_fasce(icp, SOGLIE)
    assert (fasce == "monitoraggio").all()
