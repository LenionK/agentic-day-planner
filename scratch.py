from ollama import chat
from pydantic import BaseModel, Field
from planner.llm.ollama_client import OllamaClient


class TaskDraft(BaseModel):
    title: str
    duration_min: int = Field(gt=0)
    priority: int = Field(default=3, ge=1, le=5)


class ParsedDay(BaseModel):
    tasks: list[TaskDraft]


SYSTEM = (
    "Estrai i task dalla frase dell'utente. "
    "Per ogni task: titolo breve, durata in minuti, priorità da 1 a 5. "
    "Se la durata non è indicata, stima una durata ragionevole. "
    "Priorità: 5 se l'utente usa 'devo', 'assolutamente', 'urgente'; "
    "1 se usa 'se riesco', 'magari', 'se avanza tempo'; "
    "3 in tutti gli altri casi. Non usare l'ordine dei task per decidere la priorità."
)

from planner.llm.ollama_client import OllamaClient

client = OllamaClient(model="qwen2.5:7b")
parsed = client.generate(
    messages=[
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "domani devo studiare 2 ore, poi palestra e se riesco la spesa",
        },
    ],
    schema=ParsedDay,
)
for t in parsed.tasks:
    print(t)
