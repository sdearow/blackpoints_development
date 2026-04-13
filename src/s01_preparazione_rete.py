"""Step 01 - Preparazione della rete TomTom + PGTU + semafori (Fase 0, Task 0.2 e 0.3).

Importa la rete TomTom, calcola gli indicatori di flusso e velocita' per
ciascun archetto (TGM, V_media, V85, V15, V75, V25, IQR_norm,
ratio_V85_limite), aggancia la classificazione funzionale PGTU via join
spaziale e prepara il dataset dei semafori.

Output atteso: ``data/interim/rete_tomtom_prep.gpkg``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Prepara la rete stradale arricchita con indicatori e categoria PGTU.

    TODO: implementare nello step successivo (Task 0.2 e 0.3 del piano).
    """

    raise NotImplementedError(
        "s01_preparazione_rete: da implementare (Task 0.2 e 0.3)."
    )


if __name__ == "__main__":
    main(carica_config())
