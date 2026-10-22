from types import SimpleNamespace

from ollama import ResponseError

from planner.llm.ollama_models import ModelDownloads, ensure_models, full_name


class FakeOllama:
    """Answers list() with the installed models and pull() with progress, as Ollama does.

    down: how many list() calls fail before Ollama answers; broken: models it cannot pull.
    """

    def __init__(self, installed, down=0, broken=(), downloads=None):
        self.installed = list(installed)
        self.down = down
        self.broken = set(broken)
        self.pulled: list[str] = []
        self.seen_while_pulling: list[dict] = []
        self.downloads = downloads  # per guardare lo stato mentre il download avanza

    def list(self):
        if self.down:
            self.down -= 1
            raise ConnectionError("Failed to connect to Ollama")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.installed])

    def pull(self, model, stream):
        self.pulled.append(model)
        if model in self.broken:
            raise ResponseError(f"pull model manifest: file does not exist: {model}", 500)
        yield SimpleNamespace(status="pulling manifest", completed=None, total=None)
        for done in (250, 1000):
            yield SimpleNamespace(status="pulling abc", completed=done, total=1000)
            self.seen_while_pulling.append(self.downloads.snapshot()["models"][model])
        self.installed.append(full_name(model))


def test_installed_models_are_ready_without_downloading_even_without_the_tag():
    downloads = ModelDownloads(["qwen2.5:7b", "nomic-embed-text"])
    ollama = FakeOllama(["qwen2.5:7b", "nomic-embed-text:latest"])

    ensure_models(ollama, downloads)

    assert ollama.pulled == []
    assert downloads.waiting_for() is None
    assert downloads.snapshot()["ollama"] is True


def test_a_missing_model_is_downloaded_with_its_progress():
    downloads = ModelDownloads(["qwen2.5:7b", "nomic-embed-text"])
    ollama = FakeOllama(["qwen2.5:7b"], downloads=downloads)

    ensure_models(ollama, downloads)

    assert ollama.pulled == ["nomic-embed-text"]
    assert [s["percent"] for s in ollama.seen_while_pulling] == [25, 100]
    assert {s["state"] for s in ollama.seen_while_pulling} == {"downloading"}
    assert downloads.snapshot()["models"]["nomic-embed-text"]["state"] == "ready"


def test_it_waits_for_ollama_and_tries_again():
    downloads = ModelDownloads(["qwen2.5:7b"])
    ollama = FakeOllama(["qwen2.5:7b"], down=2)
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        assert downloads.snapshot()["ollama"] is False  # mentre aspetta, la pagina lo sa

    ensure_models(ollama, downloads, retry_seconds=3.0, sleep=sleep)

    assert waits == [3.0, 3.0]
    assert downloads.snapshot()["ollama"] is True
    assert downloads.waiting_for() is None


def test_a_model_ollama_cannot_download_is_an_error_and_the_others_go_on():
    downloads = ModelDownloads(["qwen2.5:7bb", "nomic-embed-text"])
    ollama = FakeOllama([], broken={"qwen2.5:7bb"}, downloads=downloads)

    ensure_models(ollama, downloads)

    models = downloads.snapshot()["models"]
    assert models["qwen2.5:7bb"]["state"] == "error"
    assert "file does not exist" in models["qwen2.5:7bb"]["error"]
    assert models["nomic-embed-text"]["state"] == "ready"
    assert downloads.waiting_for()[0] == "qwen2.5:7bb"


def test_before_the_check_every_model_is_waited_for_in_order():
    downloads = ModelDownloads(["qwen2.5:7b", "nomic-embed-text", "qwen2.5:7b"])

    assert downloads.models == ["qwen2.5:7b", "nomic-embed-text"]  # senza doppioni
    assert downloads.waiting_for() == (
        "qwen2.5:7b",
        {"state": "checking", "percent": None, "error": None},
    )
    assert downloads.snapshot()["ollama"] is None
