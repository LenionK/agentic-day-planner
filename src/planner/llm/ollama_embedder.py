from ollama import Client

from planner.llm.embedder import Embedder


class OllamaEmbedder(Embedder):
    """Embeddings from a local Ollama model (nomic-embed-text by default in Settings).

    An embedding model does not generate text: no temperature, context or retries,
    only the model and where Ollama runs.
    """

    def __init__(self, model: str, host: str = "http://localhost:11434") -> None:
        self.model = model
        self.host = host
        self._client = Client(host=host)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        # una sola chiamata per tutti i testi; i controlli li fa embed() nella classe base
        response = self._client.embed(model=self.model, input=texts)
        return response.embeddings
