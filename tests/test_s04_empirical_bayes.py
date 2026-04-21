"""Test unitari per il calcolo Empirical Bayes ed EPDO (Fase 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.s04_empirical_bayes import (
    arricchisci_con_eb_epdo,
    calcola_eb,
    calcola_epdo,
    riassumi_eb,
)

PESI_EPDO = {"mortale": 167, "ferito_grave": 24, "ferito_lieve": 2, "solo_danni": 1}
COSTO_UNITARIO = 9000.0


# ---------------------------------------------------------------------------
# calcola_eb
# ---------------------------------------------------------------------------


def test_calcola_eb_caso_base():
    """Verifica le formule EB su un singolo sito con valori noti."""
    O = np.array([10.0])
    E = np.array([5.0])
    k = 2.0  # alpha = 0.5

    ris = calcola_eb(O, E, k)

    # w_i = 1 / (1 + 5 * 2) = 1/11
    assert ris["w_i"][0] == pytest.approx(1.0 / 11.0)
    # EB_i = (1/11)*5 + (10/11)*10 = 5/11 + 100/11 = 105/11
    assert ris["EB_i"][0] == pytest.approx(105.0 / 11.0)
    # excess = EB - E = 105/11 - 5 = 50/11
    assert ris["excess_i"][0] == pytest.approx(50.0 / 11.0)
    # var = EB * (1 - w) = (105/11) * (10/11)
    assert ris["var_EB_i"][0] == pytest.approx((105.0 / 11.0) * (10.0 / 11.0))


def test_calcola_eb_sito_nella_media():
    """Se O_i == E_i il peso non importa e EB_i == E_i == O_i."""
    O = np.array([8.0])
    E = np.array([8.0])
    ris = calcola_eb(O, E, k=1.0)
    assert ris["EB_i"][0] == pytest.approx(8.0)
    assert ris["excess_i"][0] == pytest.approx(0.0)


def test_calcola_eb_sito_pericoloso():
    """Sito con O >> E: EB deve essere maggiore di E."""
    O = np.array([50.0])
    E = np.array([5.0])
    ris = calcola_eb(O, E, k=0.5)
    assert ris["EB_i"][0] > E[0]
    assert ris["excess_i"][0] > 0


def test_calcola_eb_sito_sicuro():
    """Sito con O << E: l'eccesso e' negativo."""
    O = np.array([0.0])
    E = np.array([10.0])
    ris = calcola_eb(O, E, k=0.5)
    assert ris["excess_i"][0] < 0


def test_calcola_eb_e_nan_produce_nan():
    """Sito con E_i = NaN: tutte le stime devono essere NaN."""
    O = np.array([5.0])
    E = np.array([np.nan])
    ris = calcola_eb(O, E, k=1.0)
    assert np.isnan(ris["EB_i"][0])
    assert np.isnan(ris["excess_i"][0])


def test_calcola_eb_vettorizzato():
    """Il calcolo deve funzionare su array di N siti."""
    n = 1000
    rng = np.random.default_rng(0)
    O = rng.poisson(5, n).astype(float)
    E = rng.uniform(1, 20, n)
    k = 0.3
    ris = calcola_eb(O, E, k)
    assert len(ris["w_i"]) == n
    assert (ris["w_i"] > 0).all()
    assert (ris["w_i"] < 1).all()
    # EB deve essere tra E e O.
    assert np.all(
        (ris["EB_i"] >= np.minimum(O, E) - 1e-9)
        & (ris["EB_i"] <= np.maximum(O, E) + 1e-9)
    )


def test_calcola_eb_k_scalare_o_array():
    """k puo' essere scalare o array — risultato coerente."""
    O = np.array([10.0, 20.0])
    E = np.array([5.0, 8.0])
    ris_scal = calcola_eb(O, E, k=0.4)
    ris_arr = calcola_eb(O, E, k=np.array([0.4, 0.4]))
    np.testing.assert_allclose(ris_scal["EB_i"], ris_arr["EB_i"])


# ---------------------------------------------------------------------------
# calcola_epdo
# ---------------------------------------------------------------------------


def test_calcola_epdo_formula():
    df = pd.DataFrame(
        {
            "n_mortali": [1],
            "n_feriti_gravi": [2],
            "n_feriti_lievi": [3],
            "n_solo_danni": [4],
        }
    )
    epdo = calcola_epdo(df, PESI_EPDO)
    atteso = 1 * 167 + 2 * 24 + 3 * 2 + 4 * 1
    assert epdo.iloc[0] == pytest.approx(atteso)


def test_calcola_epdo_tutto_zero():
    df = pd.DataFrame(
        {"n_mortali": [0], "n_feriti_gravi": [0], "n_feriti_lievi": [0], "n_solo_danni": [0]}
    )
    assert calcola_epdo(df, PESI_EPDO).iloc[0] == pytest.approx(0.0)


def test_calcola_epdo_fallback_su_n_incidenti():
    """Se mancano le colonne di gravita', usa n_incidenti con peso 1."""
    df = pd.DataFrame({"n_incidenti": [10]})
    epdo = calcola_epdo(df, PESI_EPDO)
    assert epdo.iloc[0] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# arricchisci_con_eb_epdo
# ---------------------------------------------------------------------------


def _df_siti_finto(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id_sito": range(n),
            "n_incidenti": rng.poisson(5, n),
            "n_mortali": rng.binomial(1, 0.01, n),
            "n_feriti_gravi": rng.binomial(2, 0.05, n),
            "n_feriti_lievi": rng.binomial(3, 0.3, n),
            "n_solo_danni": rng.poisson(2, n),
            "E_i": rng.uniform(1, 15, n),
            "k_spf": [0.3] * n,
            "log_n_anni": [np.log(5)] * n,
        }
    )


def test_arricchisci_produce_tutte_le_colonne():
    df = _df_siti_finto()
    out = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    for col in ("w_i", "EB_i", "excess_i", "var_EB_i",
                "EPDO_i", "peso_medio_epdo", "excess_EPDO_i",
                "costo_sociale_eccesso_eur"):
        assert col in out.columns, f"colonna mancante: {col}"


def test_arricchisci_w_tra_0_e_1():
    df = _df_siti_finto()
    out = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    assert out["w_i"].between(0, 1).all()


def test_arricchisci_eb_tra_O_e_E():
    df = _df_siti_finto()
    out = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    O = out["n_incidenti"].astype(float)
    E = out["E_i"]
    assert np.all(
        (out["EB_i"] >= np.minimum(O, E) - 1e-6)
        & (out["EB_i"] <= np.maximum(O, E) + 1e-6)
    )


def test_arricchisci_costo_proporzionale_eccesso():
    """Il costo sociale deve essere proporzionale all'eccesso EPDO."""
    df = _df_siti_finto(n=10)
    out = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    np.testing.assert_allclose(
        out["costo_sociale_eccesso_eur"],
        out["excess_EPDO_i"] * COSTO_UNITARIO,
    )


# ---------------------------------------------------------------------------
# riassumi_eb
# ---------------------------------------------------------------------------


def test_riassumi_eb_struttura():
    df = _df_siti_finto()
    df_arricchito = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    r = riassumi_eb(df_arricchito, df_arricchito)
    for sezione in ("segmenti", "intersezioni"):
        assert sezione in r
        assert "n_siti" in r[sezione]
        assert "O_tot" in r[sezione]
        assert "excess_tot" in r[sezione]
        assert "EPDO_tot" in r[sezione]


def test_riassumi_eb_coerenza_totali():
    df = _df_siti_finto()
    df_arricchito = arricchisci_con_eb_epdo(df, PESI_EPDO, COSTO_UNITARIO)
    r = riassumi_eb(df_arricchito, df_arricchito)
    # O_tot deve coincidere con la somma effettiva.
    assert r["segmenti"]["O_tot"] == int(df["n_incidenti"].sum())
