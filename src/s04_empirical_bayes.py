"""Step 04 - Calcolo Empirical Bayes ed EPDO (Fase 3).

Per ogni sito (segmento o intersezione) calcola:
- Task 3.1: peso EB, stima EB, eccesso atteso, varianza EB
- Task 3.2: EPDO (Equivalent Property Damage Only), eccesso EPDO,
  costo sociale dell'eccesso in euro

Output: ``data/processed/eb_results.parquet``.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s04_empirical_bayes")


# =====================================================================
# Task 3.1 — Calcolo EB
# =====================================================================


def calcola_eb(
    O_i: np.ndarray,
    E_i: np.ndarray,
    k: float | np.ndarray,
) -> dict[str, np.ndarray]:
    """Calcola le stime Empirical Bayes per un vettore di siti.

    Formule standard EB (Hauer 1997):
    - ``w_i = 1 / (1 + E_i * k)``  (peso verso la SPF)
    - ``EB_i = w_i * E_i + (1 - w_i) * O_i``
    - ``excess_i = EB_i - E_i``
    - ``var_EB_i = EB_i * (1 - w_i)``

    Parametri
    ----------
    O_i : array degli incidenti osservati
    E_i : array delle predizioni SPF
    k   : parametro di sovradispersione NB2 (scalare o array per sito)

    Restituisce un dizionario con array numpy per ciascuna colonna.
    """
    O_i = np.asarray(O_i, dtype=float)
    E_i = np.asarray(E_i, dtype=float)
    k = np.broadcast_to(np.asarray(k, dtype=float), O_i.shape).copy()

    # Dove E_i o k sono NaN/zero, il calcolo non e' definibile.
    valido = np.isfinite(E_i) & np.isfinite(k) & (E_i > 0) & (k > 0)

    w_i = np.where(valido, 1.0 / (1.0 + E_i * k), np.nan)
    EB_i = np.where(valido, w_i * E_i + (1.0 - w_i) * O_i, np.nan)
    excess_i = np.where(valido, EB_i - E_i, np.nan)
    var_EB_i = np.where(valido, EB_i * (1.0 - w_i), np.nan)

    return {
        "w_i": w_i,
        "EB_i": EB_i,
        "excess_i": excess_i,
        "var_EB_i": var_EB_i,
    }


# =====================================================================
# Task 3.2 — EPDO e costo sociale
# =====================================================================


def calcola_epdo(
    df: pd.DataFrame,
    pesi_epdo: dict[str, float],
) -> pd.Series:
    """Calcola l'EPDO per ciascun sito.

    EPDO_i = n_mortali * peso_mortale
           + n_feriti_gravi * peso_ferito_grave
           + n_feriti_lievi * peso_ferito_lieve
           + n_solo_danni * peso_solo_danni

    Se le colonne dei conteggi per gravita' non sono presenti nel
    DataFrame, ricade su ``n_incidenti`` con peso medio = 1.
    """
    cols = {
        "mortale": "n_mortali",
        "ferito_grave": "n_feriti_gravi",
        "ferito_lieve": "n_feriti_lievi",
        "solo_danni": "n_solo_danni",
    }
    epdo = pd.Series(0.0, index=df.index)
    for gravita, col in cols.items():
        if col in df.columns:
            peso = float(pesi_epdo.get(gravita, 1.0))
            epdo += df[col].fillna(0).astype(float) * peso
        elif "n_incidenti" in df.columns:
            # Fallback: tutti gli incidenti con peso medio 1.
            epdo += df["n_incidenti"].fillna(0).astype(float)
            break
    return epdo


def arricchisci_con_eb_epdo(
    df: pd.DataFrame,
    pesi_epdo: dict[str, float],
    costo_unitario_eur: float,
) -> pd.DataFrame:
    """Aggiunge le colonne EB ed EPDO al DataFrame del sito.

    Richiede colonne ``n_incidenti``, ``E_i``, ``k_spf`` nel DataFrame.
    Aggiunge: ``w_i``, ``EB_i``, ``excess_i``, ``var_EB_i``,
    ``EPDO_i``, ``peso_medio_epdo``, ``excess_EPDO_i``,
    ``costo_sociale_eccesso_eur``.
    """
    df = df.copy()

    eb = calcola_eb(
        O_i=df["n_incidenti"].to_numpy(dtype=float),
        E_i=df["E_i"].to_numpy(dtype=float),
        k=df["k_spf"].to_numpy(dtype=float),
    )
    for col, vals in eb.items():
        df[col] = vals

    df["EPDO_i"] = calcola_epdo(df, pesi_epdo)
    # Peso medio EPDO per incidente (usato per scalare l'eccesso).
    n_inc = df["n_incidenti"].astype(float).clip(lower=1e-9)
    df["peso_medio_epdo"] = df["EPDO_i"] / n_inc
    df["excess_EPDO_i"] = df["excess_i"] * df["peso_medio_epdo"]
    df["costo_sociale_eccesso_eur"] = df["excess_EPDO_i"] * float(costo_unitario_eur)

    return df


# =====================================================================
# Riassunto e salvataggio
# =====================================================================


def riassumi_eb(df_seg: pd.DataFrame, df_int: pd.DataFrame) -> dict[str, Any]:
    """Statistiche descrittive delle stime EB."""
    r: dict[str, Any] = {}
    for nome, df in (("segmenti", df_seg), ("intersezioni", df_int)):
        mask = df["EB_i"].notna()
        sub = df.loc[mask]
        r[nome] = {
            "n_siti": int(len(df)),
            "n_con_eb": int(mask.sum()),
            "O_tot": int(df["n_incidenti"].sum()),
            "E_tot": float(df["E_i"].sum(skipna=True)),
            "EB_tot": float(sub["EB_i"].sum()),
            "excess_tot": float(sub["excess_i"].sum()),
            "n_siti_con_eccesso_positivo": int((sub["excess_i"] > 0).sum()),
            "excess_p90": float(sub["excess_i"].quantile(0.90)),
            "excess_p99": float(sub["excess_i"].quantile(0.99)),
            "excess_max": float(sub["excess_i"].max()),
            "EPDO_tot": float(df["EPDO_i"].sum()),
            "excess_EPDO_tot": float(sub["excess_EPDO_i"].sum()),
            "costo_sociale_tot_meur": float(
                sub["costo_sociale_eccesso_eur"].sum() / 1e6
            ),
        }
    return r


def salva_risultati_eb(
    df_seg: pd.DataFrame,
    df_int: pd.DataFrame,
    percorso: Path,
) -> None:
    """Salva i risultati EB in un file Parquet (due layer via suffisso)."""
    percorso.parent.mkdir(parents=True, exist_ok=True)

    percorso_seg = percorso.with_suffix("").with_name(
        percorso.stem + "_segmenti.parquet"
    )
    percorso_int = percorso.with_suffix("").with_name(
        percorso.stem + "_intersezioni.parquet"
    )

    # Assicura che le colonne geometriche non siano presenti nel Parquet.
    cols_drop = [c for c in ("geometry",) if c in df_seg.columns]
    df_seg.drop(columns=cols_drop).to_parquet(percorso_seg, index=False)
    cols_drop = [c for c in ("geometry",) if c in df_int.columns]
    df_int.drop(columns=cols_drop).to_parquet(percorso_int, index=False)

    log.info(
        "EB results salvati: %s (%d seg) e %s (%d int)",
        percorso_seg,
        len(df_seg),
        percorso_int,
        len(df_int),
    )


# =====================================================================
# Pipeline principale
# =====================================================================


def main(config: dict[str, Any]) -> None:
    """Calcola la stima Empirical Bayes e il peso EPDO per ogni sito."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Carica i risultati SPF.
    spf_path = RADICE_PROGETTO / config["paths"]["processed"]["spf_models"]
    log.info("Caricamento modelli SPF da %s", spf_path)
    with open(spf_path, "rb") as f:
        spf = pickle.load(f)

    df_seg: pd.DataFrame = spf["df_segmenti_spf"]
    df_int: pd.DataFrame = spf["df_intersezioni_spf"]
    log.info(
        "Dataset SPF: %d segmenti, %d intersezioni",
        len(df_seg),
        len(df_int),
    )

    # Parametri EPDO dal config.
    pesi_epdo: dict[str, float] = {
        k: float(v) for k, v in config["epdo"]["pesi"].items()
    }
    costo_unitario = float(config["epdo"]["costo_unitario_eur"])

    # Task 3.1 + 3.2.
    log.info("Calcolo EB e EPDO per segmenti...")
    df_seg = arricchisci_con_eb_epdo(df_seg, pesi_epdo, costo_unitario)
    log.info("Calcolo EB e EPDO per intersezioni...")
    df_int = arricchisci_con_eb_epdo(df_int, pesi_epdo, costo_unitario)

    # Riassunto.
    ris = riassumi_eb(df_seg, df_int)
    log.info("Riassunto EB:")
    for tipo, info in ris.items():
        log.info("  %s:", tipo)
        for k, v in info.items():
            log.info("    %s: %s", k, f"{v:.2f}" if isinstance(v, float) else v)

    # Salvataggio.
    out_path = RADICE_PROGETTO / config["paths"]["processed"]["eb_results"]
    salva_risultati_eb(df_seg, df_int, out_path)


if __name__ == "__main__":
    main(carica_config())
