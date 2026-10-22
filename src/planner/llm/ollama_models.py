"""The Ollama models the planner needs: checked when the API starts, downloaded if missing.

Downloading qwen2.5:7b takes minutes, so it runs in a background thread while the API
already answers: /health reports where each model stands, the page shows it, and new plans
wait until the models are ready. If Ollama does not answer, the thread tries again until it
does, so starting Ollama after the API is enough.
"""

import threading
import time
from collections.abc import Callable, Sequence

from ollama import ResponseError

RETRY_SECONDS = 5.0  # ogni quanto si riprova se Ollama non risponde


def full_name(model: str) -> str:
    """The name Ollama lists: "nomic-embed-text" -> "nomic-embed-text:latest"."""
    return model if ":" in model else f"{model}:latest"


class ModelDownloads:
    """Where each model stands, shared between the download thread and the API requests.

    state: "checking" (not known yet), "downloading" (with percent), "ready" or "error".
    ollama: None until the first answer, then whether Ollama answers.
    """

    def __init__(self, models: Sequence[str]) -> None:
        self.models = list(dict.fromkeys(models))  # senza doppioni, in ordine
        self._lock = threading.Lock()  # il thread scrive mentre le richieste leggono
        self._state = {
            m: {"state": "checking", "percent": None, "error": None} for m in self.models
        }
        self._ollama: bool | None = None

    def set(self, model: str, state: str, percent: int | None = None, error: str | None = None):
        with self._lock:
            self._state[model] = {"state": state, "percent": percent, "error": error}

    def set_ollama(self, answers: bool) -> None:
        with self._lock:
            self._ollama = answers

    def snapshot(self) -> dict:
        """A copy for /health: {"ollama": ..., "models": {name: {"state", "percent", "error"}}}."""
        with self._lock:
            return {"ollama": self._ollama, "models": {m: dict(s) for m, s in self._state.items()}}

    def waiting_for(self) -> tuple[str, dict] | None:
        """The first model that is not ready, with its state; None when all are ready."""
        with self._lock:
            for model in self.models:
                if self._state[model]["state"] != "ready":
                    return model, dict(self._state[model])
        return None


def ensure_models(
    client,
    downloads: ModelDownloads,
    retry_seconds: float = RETRY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Mark the installed models ready and download the missing ones.

    While Ollama does not answer (not started, or stopped during a download) it waits and
    tries again. A model Ollama cannot download (a wrong name in .env) is marked "error"
    with Ollama's message, and the others go on.
    """
    while True:
        try:
            installed = {full_name(m.model) for m in client.list().models}
            downloads.set_ollama(True)
            for model in downloads.models:
                if full_name(model) in installed:
                    downloads.set(model, "ready")
                    continue
                downloads.set(model, "downloading", 0)
                try:
                    for part in client.pull(model, stream=True):
                        if part.total:  # i pezzi del modello, uno alla volta: il più grande pesa
                            downloads.set(
                                model, "downloading", round(100 * part.completed / part.total)
                            )
                    downloads.set(model, "ready")
                except ResponseError as err:
                    downloads.set(model, "error", error=err.error)
            return
        except ConnectionError:
            downloads.set_ollama(False)
            sleep(retry_seconds)


def start_model_check(client, downloads: ModelDownloads) -> threading.Thread:
    """Run ensure_models in a background thread (daemon: it does not keep the server alive)."""
    thread = threading.Thread(target=ensure_models, args=(client, downloads), daemon=True)
    thread.start()
    return thread
