import time

from langchain_ollama import ChatOllama

from planner.agents.parser import SYSTEM_PROMPT, ParsedDay
from planner.config import Settings

settings = Settings()

llm = ChatOllama(
    model=settings.llm_model,
    base_url=settings.ollama_host,
    temperature=0,
    num_ctx=settings.llm_num_ctx,
    num_predict=2048,
    repeat_penalty=1.0,
    format=ParsedDay.model_json_schema(),
)

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {
        "role": "user",
        "content": "domani devo studiare 2 ore, dentista alle 15 e se riesco la spesa",
    },
]

start = time.perf_counter()
response = llm.invoke(messages)
elapsed = time.perf_counter() - start

print("Tipo della risposta:", type(response).__name__)
print("Testo grezzo:\n", response.content)
print(f"\nTempo: {elapsed:.1f} s")

parsed = ParsedDay.model_validate_json(response.content)
for t in parsed.tasks:
    print(t)
