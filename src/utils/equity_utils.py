"""Misure di equita' distributiva per il modulo Equita' (WP2 del PSS).

Statistiche sul rapporto tra *dotazione* di interventi di sicurezza
stradale e *bisogno* (vulnerabilita' sociale x rischio) per unita'
territoriale:

- ``gini`` / ``curva_lorenz``     : disuguaglianza della dotazione
  pro-capite (equita' orizzontale);
- ``concentration_index``         : la dotazione si concentra sulle unita'
  a piu' alto o piu' basso bisogno? (equita' verticale - la statistica
  centrale del paper: CI < 0 = interventi concentrati dove il bisogno
  e' basso);
- ``lisa_bivariata``              : cluster spaziali bisogno x dotazione
  (quadrante High-Low = alto bisogno servito poco -> mismatch);
- ``classifica_bivariata``        : classi 3x3 per la choropleth bivariata;
- ``equity_priority_zones``       : flag delle aree prioritarie.

Convenzioni: tutte le funzioni accettano array/Series allineati per
unita' territoriale; i pesi di popolazione servono a far contare ogni
*persona* (non ogni unita') allo stesso modo.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger("equity_utils")


# =====================================================================
# Disuguaglianza distributiva (Lorenz / Gini / concentration index)
# =====================================================================


def _valida_input(
    valori: np.ndarray, pesi: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(valori, dtype=float)
    w = np.ones_like(v) if pesi is None else np.asarray(pesi, dtype=float)
    if v.shape != w.shape:
        raise ValueError("valori e pesi devono avere la stessa lunghezza")
    ok = np.isfinite(v) & np.isfinite(w) & (w >= 0)
    return v[ok], w[ok]


def curva_lorenz(
    dotazione: np.ndarray, peso_pop: np.ndarray | None = None
) -> pd.DataFrame:
    """Curva di Lorenz della dotazione.

    Ordina le unita' per dotazione pro-capite crescente e cumula:
    ritorna ``frac_pop`` (quota cumulata di popolazione) e ``frac_dotazione``
    (quota cumulata di dotazione). La diagonale e' l'equidistribuzione.
    """
    v, w = _valida_input(dotazione, peso_pop)
    if len(v) == 0 or w.sum() <= 0:
        return pd.DataFrame({"frac_pop": [0.0, 1.0], "frac_dotazione": [0.0, 1.0]})

    procapite = np.divide(v, w, out=np.zeros_like(v), where=w > 0)
    ordine = np.argsort(procapite, kind="stable")
    w_ord, v_ord = w[ordine], v[ordine]

    frac_pop = np.concatenate([[0.0], np.cumsum(w_ord) / w_ord.sum()])
    tot = v_ord.sum()
    frac_dot = (
        np.concatenate([[0.0], np.cumsum(v_ord) / tot])
        if tot > 0
        else np.zeros(len(v_ord) + 1)
    )
    return pd.DataFrame({"frac_pop": frac_pop, "frac_dotazione": frac_dot})


def gini(dotazione: np.ndarray, peso_pop: np.ndarray | None = None) -> float:
    """Indice di Gini pesato per popolazione sulla dotazione pro-capite.

    0 = dotazione pro-capite identica ovunque; 1 = tutta la dotazione in
    una sola unita'. Calcolato come 1 - 2 * area sotto la Lorenz
    (integrazione trapezoidale, esatta per la curva spezzata).
    Convenzione: dotazione totale nulla -> 0 (nulla da distribuire).
    """
    v, _ = _valida_input(dotazione, peso_pop)
    if len(v) == 0 or v.sum() <= 0:
        return 0.0
    curva = curva_lorenz(dotazione, peso_pop)
    area = float(np.trapezoid(curva["frac_dotazione"], curva["frac_pop"]))
    return max(0.0, min(1.0, 1.0 - 2.0 * area))


def concentration_index(
    dotazione: np.ndarray,
    bisogno: np.ndarray,
    peso_pop: np.ndarray | None = None,
) -> float:
    """Concentration index della dotazione rispetto al ranking di bisogno.

    Adattamento della letteratura sanitaria (Wagstaff/O'Donnell): le unita'
    sono ordinate per *bisogno crescente* e si misura se la dotazione
    pro-capite si concentra in alto o in basso nel ranking:

        CI = 2 * cov_w(y, r) / media_w(y)

    con ``y`` dotazione pro-capite, ``r`` rango frazionale pesato del
    bisogno. Range [-1, 1]:
    - **CI > 0**: dotazione concentrata sulle unita' a bisogno alto
      (pro-bisogno: equita' verticale rispettata);
    - **CI < 0**: dotazione concentrata dove il bisogno e' basso
      (pro-avvantaggiati: iniquita' verticale).
    """
    v, w = _valida_input(dotazione, peso_pop)
    b = np.asarray(bisogno, dtype=float)
    if peso_pop is None:
        b_ok = b[np.isfinite(np.asarray(dotazione, dtype=float))]
    else:
        ok = (
            np.isfinite(np.asarray(dotazione, dtype=float))
            & np.isfinite(np.asarray(peso_pop, dtype=float))
            & (np.asarray(peso_pop, dtype=float) >= 0)
        )
        b_ok = b[ok]
    if len(v) == 0 or w.sum() <= 0:
        return 0.0

    y = np.divide(v, w, out=np.zeros_like(v), where=w > 0)

    # Rango frazionale pesato del bisogno (Lerman & Yitzhaki 1989).
    ordine = np.argsort(b_ok, kind="stable")
    w_ord = w[ordine]
    w_norm = w_ord / w_ord.sum()
    r_ord = np.cumsum(w_norm) - 0.5 * w_norm
    r = np.empty_like(r_ord)
    r[ordine] = r_ord

    mu = float(np.average(y, weights=w))
    if mu == 0:
        return 0.0
    cov = float(np.average((y - np.average(y, weights=w)) * (r - 0.5), weights=w))
    return max(-1.0, min(1.0, 2.0 * cov / mu))


# =====================================================================
# Cluster spaziali (LISA bivariata) e classificazione bivariata
# =====================================================================


def lisa_bivariata(
    gdf: gpd.GeoDataFrame,
    col_bisogno: str,
    col_dotazione: str,
    k_vicini: int = 8,
    p_max: float = 0.05,
    seed: int = 42,
    permutazioni: int = 999,
) -> pd.DataFrame:
    """Moran locale bivariato: bisogno (x) vs dotazione nei vicini (Wy).

    Pesi spaziali KNN (robusti a unita' senza contigui). Ritorna, con lo
    stesso indice di ``gdf``:
    - ``lisa_quadrante``: ``HH``/``HL``/``LH``/``LL`` (High-Low = alto
      bisogno circondato da bassa dotazione -> il mismatch cercato);
    - ``lisa_p``: pseudo p-value (permutazioni condizionali);
    - ``lisa_sig``: quadrante se p <= p_max, altrimenti ``ns``.
    """
    from esda.moran import Moran_Local_BV
    from libpysal.weights import KNN

    if len(gdf) <= k_vicini:
        raise ValueError(f"Servono piu' di {k_vicini} unita' per KNN")

    w = KNN.from_dataframe(gdf, k=k_vicini)
    w.transform = "r"

    ml = Moran_Local_BV(
        gdf[col_bisogno].to_numpy(dtype=float),
        gdf[col_dotazione].to_numpy(dtype=float),
        w,
        permutations=permutazioni,
        seed=seed,
    )
    mappa_q = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}
    out = pd.DataFrame(index=gdf.index)
    out["lisa_quadrante"] = pd.Series(ml.q, index=gdf.index).map(mappa_q)
    out["lisa_p"] = ml.p_sim
    out["lisa_sig"] = np.where(out["lisa_p"] <= p_max, out["lisa_quadrante"], "ns")
    return out


def classifica_bivariata(
    bisogno: pd.Series,
    dotazione: pd.Series,
    n_classi: int = 3,
) -> pd.Series:
    """Classi per choropleth bivariata: terzili bisogno x terzili dotazione.

    Ritorna stringhe ``"{i}-{j}"`` con i = classe di bisogno (1=basso,
    n=alto) e j = classe di dotazione. ``"3-1"`` = alto bisogno, bassa
    dotazione. I quantili degeneri (molti zeri) vengono gestiti con
    ``duplicates="drop"`` e la classe piu' bassa come default.
    """
    def _classi(serie: pd.Series) -> pd.Series:
        s = serie.fillna(0).astype(float)
        try:
            c = pd.qcut(s, q=n_classi, labels=False, duplicates="drop")
        except ValueError:
            c = pd.Series(0, index=s.index)
        return c.fillna(0).astype(int) + 1

    cb = _classi(bisogno)
    cd = _classi(dotazione)
    return cb.astype(str) + "-" + cd.astype(str)


def equity_priority_zones(
    bisogno: pd.Series,
    dotazione: pd.Series,
    lisa: pd.DataFrame | None = None,
    n_classi: int = 3,
) -> pd.Series:
    """Flag delle equity priority zones.

    Una unita' e' prioritaria se:
    - e' nel terzile di bisogno piu' alto E nel terzile di dotazione piu'
      basso (classe ``"3-1"`` della choropleth bivariata), OPPURE
    - e' un cluster LISA ``HL`` significativo (se ``lisa`` e' fornita).
    """
    classe = classifica_bivariata(bisogno, dotazione, n_classi=n_classi)
    prioritarie = classe == f"{n_classi}-1"
    if lisa is not None and "lisa_sig" in lisa.columns:
        prioritarie = prioritarie | (lisa["lisa_sig"] == "HL")
    return prioritarie
