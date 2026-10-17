from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


# 1. Lo stato: tutto quello che il flusso sa
class OrderState(TypedDict):
    items: list[str]
    total: float
    status: str


PRICES = {"pizza": 9.0, "birra": 5.0, "tiramisù": 6.0}


# 2. I nodi: ricevono lo stato, restituiscono solo i campi che cambiano
def compute_total(state: OrderState) -> dict:
    total = sum(PRICES[item] for item in state["items"])
    print(f"[compute_total] totale {total}")
    return {"total": total}


def ask_approval(state: OrderState) -> dict:
    print("[ask_approval] eseguito")  # guarda quante volte compare alla ripresa
    answer = interrupt(f"Il conto è {state['total']} €. Confermi?")
    return {"status": "approvato" if answer == "sì" else "annullato"}


def place_order(state: OrderState) -> dict:
    if state["status"] == "annullato":
        return {}
    return {"status": "inviato in cucina"}


# 3. L'arco condizionale: guarda lo stato e restituisce il nome del nodo successivo
def needs_approval(state: OrderState) -> str:
    return "ask_approval" if state["total"] > 20 else "place_order"


# 4. Il grafo
builder = StateGraph(OrderState)
builder.add_node("compute_total", compute_total)
builder.add_node("ask_approval", ask_approval)
builder.add_node("place_order", place_order)

builder.add_edge(START, "compute_total")
builder.add_edge("ask_approval", "place_order")
builder.add_edge("ask_approval", "editor")
builder.add_edge("place_order", END)

graph = builder.compile(checkpointer=InMemorySaver())


# 5. Esecuzione
config = {"configurable": {"thread_id": "tavolo-7"}}

result = graph.invoke(
    {"items": ["pizza", "pizza", "birra"], "total": 0.0, "status": "nuovo"}, config
)

if "__interrupt__" in result:
    question = result["__interrupt__"][0].value
    print("Il grafo chiede:", question)
    result = graph.invoke(Command(resume="no"), config)

print("Stato finale:", result)
