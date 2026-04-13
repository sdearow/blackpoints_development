"""Step 04 - Calcolo Empirical Bayes ed EPDO (Fase 3).

Per ogni sito calcola il peso EB ``w_i = 1 / (1 + E_i * k)``, la stima EB
``EB_i = w_i * E_i + (1 - w_i) * O_i``, l'eccesso atteso e la varianza
associata. Applica la pesatura per gravita' (EPDO) usando i pesi configurati
in ``config.yaml`` (Task 3.2 del piano).

Output atteso: ``data/processed/eb_results.parquet``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Calcola la stima Empirical Bayes e il peso EPDO per ogni sito.

    TODO: implementare (Fase 3, Task 3.1 e 3.2).
    """

    raise NotImplementedError(
        "s04_empirical_bayes: da implementare (Fase 3)."
    )


if __name__ == "__main__":
    main(carica_config())
