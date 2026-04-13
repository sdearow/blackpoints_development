"""Step 02 - Matching spaziale incidenti <-> rete (Fase 1).

Estrae le intersezioni dai nodi della rete TomTom, costruisce i segmenti
omogenei tra intersezioni e assegna ogni incidente a un'intersezione o a un
segmento secondo i criteri descritti nel Task 1.3 del piano (snap geometrico,
match toponomastico fuzzy, soglie configurabili).

Output atteso: ``data/interim/intersezioni.gpkg``,
``data/interim/segmenti.gpkg``, ``data/interim/incidenti_matched.gpkg``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Esegue il matching spaziale tra incidenti e rete.

    TODO: implementare (Fase 1, Task 1.1, 1.2, 1.3).
    """

    raise NotImplementedError(
        "s02_matching: da implementare (Fase 1)."
    )


if __name__ == "__main__":
    main(carica_config())
