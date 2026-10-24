"""Non-blocking cache for installed, user-selected module plug-ins."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable


class ModuleDataProvider:
    """Run installed module entry points off the Qt thread and cache their values."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="osclinux-module")
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], str] = {}
        self._next_refresh: dict[tuple[str, str], float] = {}
        self._pending: set[tuple[str, str]] = set()

    def get(
        self,
        module_id: str,
        options: dict,
        loader: Callable[[], str],
        refresh_interval: float = 2.0,
    ) -> str:
        signature = json.dumps(options, ensure_ascii=False, sort_keys=True, default=str)
        cache_key = (module_id, signature)
        with self._lock:
            value = self._values.get(cache_key, "Chargement…")
            if time.monotonic() >= self._next_refresh.get(cache_key, 0) and cache_key not in self._pending:
                self._next_refresh[cache_key] = time.monotonic() + max(0.1, refresh_interval)
                self._pending.add(cache_key)
                future = self._executor.submit(loader)
                future.add_done_callback(lambda result, key=cache_key: self._complete(key, result))
            return value

    def _complete(self, key: tuple[str, str], future: Future) -> None:
        try:
            result = future.result()
            value = result if isinstance(result, str) else "Le module a renvoyé une valeur invalide."
        except Exception as exc:
            value = f"Module indisponible : {exc}"
        with self._lock:
            self._values[key] = value
            self._pending.discard(key)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
