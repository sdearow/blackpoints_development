"""Step 05 - Indice composito di priorita' (Fase 4).

Calcola le quattro componenti dell'indice (eccesso EB pesato, severita',
vulnerabilita' utenti, rischio velocita'), le normalizza su scala 0-100 con
percentili robusti, le combina nell'indice composito ``ICP`` con i pesi
configurabili e classifica i siti in fasce di priorita'. Costruisce inoltre
la matrice di rischio 2x2 e l'analisi di sensibilita' sui pesi.

Output atteso: ``data/processed/priorita_finale.gpkg``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Calcola l'indice composito e classifica i siti in fasce di priorita'.

    TODO: implementare (Fase 4, Task 4.1, 4.2, 4.3, 4.4).
    """

    raise NotImplementedError(
        "s05_indice_composito: da implementare (Fase 4)."
    )


if __name__ == "__main__":
    main(carica_config())
