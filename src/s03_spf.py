"""Step 03 - Calibrazione delle Safety Performance Functions (Fase 2).

Costruisce il dataset di regressione per segmenti e intersezioni, calibra i
modelli binomiali negativi (NB2) per ciascuna categoria funzionale e
intersezioni semaforizzate/non semaforizzate, produce diagnostica (residui,
CURE plot, test di Freeman-Tukey) e salva i coefficienti calibrati.

Output atteso: ``data/processed/spf_models.pkl``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Calibra le SPF e salva i modelli.

    TODO: implementare (Fase 2, Task 2.1, 2.2, 2.3).
    """

    raise NotImplementedError(
        "s03_spf: da implementare (Fase 2)."
    )


if __name__ == "__main__":
    main(carica_config())
