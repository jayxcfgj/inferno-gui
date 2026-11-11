"""Pure Lock-Logik: erkennt, wann der PTP-Sync stabil ist.

Keine Qt-Abhaengigkeiten - die Klasse ist komplett testbar ohne UI.
"""

from __future__ import annotations


class LockGate:
    """Zaehlt aufeinanderfolgende PTP-Ticks im Zielzustand und signalisiert Lock.

    Ein Treffer ist ein Tick mit ``state == 'SLAVE'`` und einer Offset-Messung
    ``offset_ns <= threshold_ns``. Jeder Nicht-Treffer setzt den Zaehler auf 0.
    Sobald ``required_ticks`` Treffer in Folge erreicht sind, liefert ``feed``
    True (sticky bis ``reset()``).
    """

    def __init__(self, threshold_ns: int, required_ticks: int) -> None:
        self.threshold_ns = threshold_ns
        self.required_ticks = required_ticks
        self._count = 0
        self._locked = False

    @property
    def stable_count(self) -> int:
        """Anzahl aufeinanderfolgender Treffer (wird bei Nicht-Treffern auf 0 gesetzt)."""
        return self._count

    def feed(self, state: str | None, offset_ns: int | None) -> bool:
        """Einen PTP-Tick einspeisen. True, sobald der Lock erreicht ist (sticky)."""
        hit = state == 'SLAVE' and offset_ns is not None and offset_ns <= self.threshold_ns
        if hit:
            self._count += 1
        else:
            self._count = 0
        if self._count >= self.required_ticks:
            self._locked = True
        return self._locked

    def reset(self) -> None:
        """Zaehler und Lock-Zustand zuruecksetzen."""
        self._count = 0
        self._locked = False
