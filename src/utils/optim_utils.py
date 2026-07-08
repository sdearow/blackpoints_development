"""Formulazione e solver del Maximal Covering Location Problem (WP3).

MCLP (Church & ReVelle 1974):

    max  sum_i d_i * y_i
    s.t. y_i <= sum_{j in N_i} x_j     (i coperto solo se un candidato vicino e' scelto)
         sum_j x_j <= p                (budget: numero di interventi)
         x_j, y_i in {0, 1}

dove ``d_i`` e' la domanda del punto i (rischio/bisogno pesati) e ``N_i``
l'insieme dei candidati che lo coprono entro il raggio.

Due solver:
- :func:`risolvi_mclp_esatto` - ILP con PuLP/CBC (ottimo garantito,
  con timeout);
- :func:`risolvi_mclp_greedy` - euristica greedy (garanzia 1-1/e per
  la copertura massimale), usata come fallback e per i test di sanita'.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

log = logging.getLogger("optim_utils")


def costruisci_copertura(
    xy_candidati: np.ndarray,
    xy_domanda: np.ndarray,
    raggio_m: float,
) -> sparse.csr_matrix:
    """Matrice sparsa di copertura ``a[i, j] = 1`` se il candidato j
    copre il punto di domanda i (distanza euclidea <= raggio, CRS metrico).

    ``xy_candidati``: (n_cand, 2); ``xy_domanda``: (n_dom, 2).
    """
    albero_cand = cKDTree(xy_candidati)
    albero_dom = cKDTree(xy_domanda)
    # Per ogni domanda, i candidati entro il raggio.
    coppie = albero_dom.query_ball_tree(albero_cand, r=float(raggio_m))
    righe, colonne = [], []
    for i, vicini in enumerate(coppie):
        righe.extend([i] * len(vicini))
        colonne.extend(vicini)
    n_dom, n_cand = len(xy_domanda), len(xy_candidati)
    dati = np.ones(len(righe), dtype=np.int8)
    return sparse.csr_matrix((dati, (righe, colonne)), shape=(n_dom, n_cand))


def risolvi_mclp_greedy(
    domanda: np.ndarray,
    copertura: sparse.csr_matrix,
    p: int,
) -> dict[str, Any]:
    """Euristica greedy: a ogni passo sceglie il candidato che aggiunge
    piu' domanda scoperta. Garanzia teorica (1 - 1/e) ~ 63% dell'ottimo;
    in pratica molto vicina all'ottimo su istanze spaziali."""
    domanda = np.asarray(domanda, dtype=float)
    cop_csc = copertura.tocsc()
    coperto = np.zeros(len(domanda), dtype=bool)
    scelti: list[int] = []

    for _ in range(int(p)):
        residuo = np.where(coperto, 0.0, domanda)
        # Guadagno di ciascun candidato = domanda residua che coprirebbe.
        guadagni = cop_csc.T @ residuo
        if len(scelti):
            guadagni[np.asarray(scelti)] = -1.0
        j = int(np.argmax(guadagni))
        if guadagni[j] <= 0:
            break
        scelti.append(j)
        coperto |= np.asarray(cop_csc[:, j].todense()).ravel() > 0

    return {
        "scelti": scelti,
        "domanda_coperta": float(domanda[coperto].sum()),
        "coperto": coperto,
        "metodo": "greedy",
        "ottimo_garantito": False,
    }


def risolvi_mclp_esatto(
    domanda: np.ndarray,
    copertura: sparse.csr_matrix,
    p: int,
    timeout_s: int = 120,
) -> dict[str, Any]:
    """MCLP esatto con PuLP/CBC. Se il solver non chiude entro il timeout
    ritorna comunque la migliore soluzione trovata (gap non nullo);
    se PuLP non e' disponibile, fallback greedy."""
    try:
        import pulp
    except ImportError:
        log.warning("PuLP non disponibile: fallback greedy.")
        return risolvi_mclp_greedy(domanda, copertura, p)

    domanda = np.asarray(domanda, dtype=float)
    n_dom, n_cand = copertura.shape

    prob = pulp.LpProblem("MCLP", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x_{j}", cat="Binary") for j in range(n_cand)]
    y = [pulp.LpVariable(f"y_{i}", cat="Binary") for i in range(n_dom)]

    prob += pulp.lpSum(float(domanda[i]) * y[i] for i in range(n_dom))
    prob += pulp.lpSum(x) <= int(p)

    cop_lil = copertura.tolil()
    for i in range(n_dom):
        vicini = cop_lil.rows[i]
        if vicini:
            prob += y[i] <= pulp.lpSum(x[j] for j in vicini)
        else:
            prob += y[i] == 0

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=int(timeout_s))
    prob.solve(solver)

    scelti = [j for j in range(n_cand) if (x[j].value() or 0) > 0.5]
    coperto = np.array([bool((y[i].value() or 0) > 0.5) for i in range(n_dom)])
    return {
        "scelti": scelti,
        "domanda_coperta": float(domanda[coperto].sum()),
        "coperto": coperto,
        "metodo": "cbc",
        "ottimo_garantito": pulp.LpStatus[prob.status] == "Optimal",
    }


def risolvi_mclp(
    domanda: np.ndarray,
    copertura: sparse.csr_matrix,
    p: int,
    metodo: str = "esatto",
    timeout_s: int = 120,
) -> dict[str, Any]:
    """Dispatcher: ``metodo`` in {"esatto", "greedy"}."""
    if metodo == "greedy":
        return risolvi_mclp_greedy(domanda, copertura, p)
    if metodo == "esatto":
        return risolvi_mclp_esatto(domanda, copertura, p, timeout_s=timeout_s)
    raise ValueError(f"metodo non riconosciuto: {metodo!r}")
