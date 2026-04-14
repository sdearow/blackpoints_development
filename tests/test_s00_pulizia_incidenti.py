"""Test unitari per le funzioni di pulizia degli incidenti (Task 0.1)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.s00_pulizia_incidenti import (
    calcola_flag_qualita,
    classifica_gravita,
    filtra_periodo,
    normalizza_nome_strada,
    parsa_datetime,
    standardizza_colonne,
)


# ---------------------------------------------------------------------------
# normalizza_nome_strada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_", "atteso"),
    [
        ("V. TIBERINA", "Via Tiberina"),
        ("VIA DI CASAL SELCE", "Via di Casal Selce"),
        ("V.le di Trastevere", "Viale di Trastevere"),
        ("P.le Flaminio", "Piazzale Flaminio"),
        ("P.zza Venezia", "Piazza Venezia"),
        ("L.go Preneste", "Largo Preneste"),
        ("  VIA   APPIA  ", "Via Appia"),
        ("", None),
        (None, None),
    ],
)
def test_normalizza_nome_strada(input_, atteso):
    assert normalizza_nome_strada(input_) == atteso


# ---------------------------------------------------------------------------
# classifica_gravita
# ---------------------------------------------------------------------------


def test_classifica_gravita_mortale_prevale():
    df = pd.DataFrame(
        {
            "n_morti": [1, 0, 0, 0],
            "n_feriti": [2, 3, 0, 0],
        }
    )
    risultato = classifica_gravita(df)["gravita"].tolist()
    assert risultato == ["mortale", "ferito_lieve", "solo_danni", "solo_danni"]


def test_classifica_gravita_con_nan():
    df = pd.DataFrame(
        {
            "n_morti": [pd.NA, 0],
            "n_feriti": [pd.NA, pd.NA],
        }
    )
    risultato = classifica_gravita(df)["gravita"].tolist()
    assert risultato == ["solo_danni", "solo_danni"]


# ---------------------------------------------------------------------------
# calcola_flag_qualita
# ---------------------------------------------------------------------------


def test_flag_qualita_alta_media_bassa():
    df = pd.DataFrame(
        {
            "x": [1.0, 2.0, None, 3.0, 4.0],
            "y": [1.0, 2.0, None, 3.0, 4.0],
            "ok": pd.array([True, True, True, False, True], dtype="boolean"),
            "approx": [None, "50", None, None, None],
            "localizzazione2": [
                "all'intersezione con",
                "all'intersezione con",
                "in corrispondenza",
                "in corrispondenza",
                "da specificare",
            ],
        }
    )
    risultato = calcola_flag_qualita(df)["flag_qualita"].tolist()
    # riga 0: ok + approx null + localizzazione specifica -> alta
    # riga 1: ok ma approx non null -> media
    # riga 2: coordinate mancanti -> bassa
    # riga 3: ok False -> bassa
    # riga 4: ok + approx null ma localizzazione 'da specificare' -> media
    assert risultato == ["alta", "media", "bassa", "bassa", "media"]


# ---------------------------------------------------------------------------
# parsa_datetime
# ---------------------------------------------------------------------------


def test_parsa_datetime_estrae_componenti():
    df = pd.DataFrame(
        {
            "data_ora": ["2019-03-18 08:30:00", "2020-11-05 22:15:00"],
            "data_conferma": ["2019-04-01 10:00:00+01", "2020-12-01 10:00:00+01"],
            "anno": pd.array([pd.NA, pd.NA], dtype="Int64"),
        }
    )
    risultato = parsa_datetime(df)

    assert risultato.loc[0, "anno"] == 2019
    assert risultato.loc[0, "mese"] == 3
    # 18 marzo 2019 era un lunedi'
    assert risultato.loc[0, "giorno_settimana"] == 0
    assert risultato.loc[0, "ora"] == 8
    assert risultato.loc[0, "fascia_oraria"] == "mattina"

    assert risultato.loc[1, "fascia_oraria"] == "sera"


# ---------------------------------------------------------------------------
# filtra_periodo
# ---------------------------------------------------------------------------


def test_filtra_periodo_noop_se_null():
    df = pd.DataFrame({"anno": [2015, 2018, 2021]})
    risultato = filtra_periodo(df, anno_inizio=None, anno_fine=None)
    assert len(risultato) == 3


def test_filtra_periodo_taglia_range():
    df = pd.DataFrame({"anno": [2015, 2018, 2021, 2024]})
    risultato = filtra_periodo(df, anno_inizio=2017, anno_fine=2021)
    assert risultato["anno"].tolist() == [2018, 2021]


# ---------------------------------------------------------------------------
# standardizza_colonne (integrazione leggera)
# ---------------------------------------------------------------------------


def test_standardizza_colonne_rinomina_e_casta():
    df_grezzo = pd.DataFrame(
        {
            "idprotocollo": ["1", "2"],
            "dataoraincidente": ["2019-03-18 08:30:00", "2020-11-05 22:15:00"],
            "anno": ["2019", "2020"],
            "num_morti": ["0", "1"],
            "num_feriti": ["2", "0"],
            "num_riservata": ["0", "0"],
            "num_illesi": ["1", "0"],
            "num_veicoli": ["2", "1"],
            "costo_sociale": ["12000", "1500000"],
            "flow": ["365", None],
            "speed": ["45", None],
            "x": ["2313372.72", "2319661.14"],
            "y": ["4654564.79", "4639554.75"],
            "ok": ["t", "f"],
            "approx": [None, "1"],
            "strada1": ["V. TIBERINA", "V.le di Trastevere"],
            "confermato": ["1", "0"],
            "danniacoseyn": ["0", "1"],
            "dataconferma": ["2019-04-01 10:00:00+01", "2020-12-01 10:00:00+01"],
            "localizzazione1": ["in corrispondenza", None],
        }
    )
    df = standardizza_colonne(df_grezzo)
    assert "id_incidente" in df.columns
    assert df["n_morti"].tolist() == [0, 1]
    assert df["x"].iloc[0] == pytest.approx(2313372.72)
    assert df["ok"].iloc[0] is True or df["ok"].iloc[0] == True  # noqa: E712
    assert df["ok"].iloc[1] is False or df["ok"].iloc[1] == False  # noqa: E712
    assert df["strada1"].iloc[0] == "Via Tiberina"
    assert df["strada1"].iloc[1] == "Viale di Trastevere"
