"""Cuota compartida de la demo; nunca registra preguntas, usuarios ni credenciales."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime


class DemoLimitError(RuntimeError):
    pass


class DemoQuota:
    def __init__(
        self,
        *,
        per_minute: int = 2,
        per_day: int = 30,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        if per_minute < 1 or per_day < 1:
            raise ValueError("Cuota inválida.")
        self.per_minute = per_minute
        self.per_day = per_day
        self.clock = clock
        self.today = today
        self._flight = threading.Lock()
        self._recent: deque[float] = deque()
        self._day: date | None = None
        self._count = 0

    @contextmanager
    def reserve(self) -> Iterator[None]:
        if not self._flight.acquire(blocking=False):
            raise DemoLimitError(
                "La IA de la demo está atendiendo otra consulta. Inténtalo en unos segundos."
            )
        try:
            now = self.clock()
            day = self.today()
            if self._day != day:
                self._day, self._count = day, 0
            while self._recent and self._recent[0] <= now - 60:
                self._recent.popleft()
            if self._count >= self.per_day:
                raise DemoLimitError(
                    "Se ha alcanzado la cuota diaria de la demo. Usa Chat guiado o conecta tu propia API."
                )
            if len(self._recent) >= self.per_minute:
                raise DemoLimitError(
                    "La demo permite dos preguntas por minuto entre todos sus visitantes. Espera un minuto o usa Chat guiado."
                )
            self._count += 1
            self._recent.append(now)
            yield
        finally:
            self._flight.release()
