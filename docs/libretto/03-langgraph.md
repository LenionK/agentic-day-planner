# 3. LangChain e LangGraph

> Versioni nel progetto: **langgraph 1.2.14** (con langgraph-checkpoint 4.2.0),
> **langchain-core 1.6.10**, **langchain-ollama 1.1.0**. Sono librerie che cambiano spesso:
> gli esempi di questo capitolo sono stati provati su queste versioni.

## Cos'è

**LangChain** è una libreria che mette un'interfaccia comune davanti a tanti modelli
linguistici (Ollama, OpenAI, Anthropic…) e a tutto quello che ci gira intorno: prompt,
messaggi, strumenti, recupero di documenti. Il suo mattone è il **Runnable**, un oggetto che
si può eseguire con `invoke`, su più input con `batch`, o pezzo per pezzo con `stream`; i
Runnable si concatenano con `|`.

**LangGraph**, della stessa squadra, serve a un'altra cosa: descrivere un **flusso di lavoro
come un grafo**. Ogni passo è un **nodo** (una funzione Python), le frecce tra i passi sono
**archi**, e tutti i nodi leggono e scrivono uno **stato** condiviso. Gli archi possono
dipendere dallo stato (vai di qua o di là), formare **cicli** (torna indietro e riprova), e il
grafo può **fermarsi ad aspettare una persona** e riprendere giorni dopo da dove era rimasto.

È quello che si chiama un *agentic workflow*: non un agente che decide da solo cosa fare, ma
un percorso di passi definito da noi, in cui alcuni passi usano un LLM e altri chiedono
all'utente.

## Perché qui

Il planner è fatto di passi diversi (un LLM che legge la frase, l'utente che controlla, un
solver che pianifica, un LLM che critica, un database che salva) con percorsi che dipendono
dai risultati: se un task non entra si chiede all'utente, se due task obbligatori si
scontrano si torna alle correzioni. Scriverlo come una catena di `if` dentro una funzione
lunga sarebbe possibile, ma due cose diventerebbero difficili:

- **le pause**: tra la domanda e la risposta dell'utente può passare un minuto o un giorno, e
  nel frattempo il programma non può restare fermo in una funzione. LangGraph salva lo stato
  a ogni passo (con un *checkpointer*) e riprende quando arriva la risposta;
- **la forma del flusso**: nel grafo i passi e i percorsi sono dichiarati, si possono
  disegnare e testare uno per uno.

Di **LangChain** il progetto usa poco, di proposito: `ChatOllama` come alternativa al client
Ollama diretto (si sceglie con `LLM_PROVIDER` in `.env`), e il tipo `RunnableConfig`, che
LangGraph usa per il contesto di ogni esecuzione. La validazione delle risposte e il ciclo di
correzione restano nostri, in `LLMClient` ([capitolo 2](02-ollama-llm.md)): sono il cuore
dell'affidabilità del progetto, e così funzionano allo stesso modo con qualunque client.

## LangChain: i concetti che servono

### Un modello di chat è un Runnable

```python
from langchain_ollama import ChatOllama

llm = ChatOllama(model="qwen2.5:7b", temperature=0, format=Mood.model_json_schema())
reply = llm.invoke([
    ("system", "Valuta l'umore della frase. Rispondi solo con il JSON richiesto."),
    ("human", "domani ho tre esami e poi il dentista"),
])
reply.content            # il testo della risposta (qui un JSON)
reply.response_metadata  # durata, token generati, modello...
```

`invoke` restituisce un `AIMessage`. I messaggi si possono scrivere come coppie
(`"system"`, `"human"`) o come oggetti (`SystemMessage`, `HumanMessage`). `format` è lo stesso
JSON Schema che il client diretto passa a Ollama.

### Catene con `|` e prompt con segnaposto

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "Valuta l'umore della frase. Rispondi solo con il JSON richiesto."),
    ("human", "{sentence}"),
])
chain = prompt | llm                      # un RunnableSequence: prompt, poi modello
chain.invoke({"sentence": "domani festa al mare"})
```

Il simbolo `|` collega due Runnable: l'uscita del primo è l'ingresso del secondo. È comodo
per catene lineari; per un flusso con scelte, cicli e pause serve LangGraph.

### Output strutturato già pronto

```python
structured = ChatOllama(model="qwen2.5:7b", temperature=0).with_structured_output(Mood)
structured.invoke("Valuta l'umore: domani dentista alle 8 e poi esame")   # -> un oggetto Mood
```

`with_structured_output` fa da sola quello che nel progetto fa `LLMClient.generate`: schema,
validazione, oggetto Pydantic. Il progetto non la usa perché il nostro ciclo **rimanda
all'LLM l'errore di validazione** e gli chiede di correggersi, e perché vogliamo lo stesso
comportamento anche con il client Ollama diretto.

## LangGraph: i concetti chiave

### Lo stato, i nodi, gli archi

```python
from typing import NotRequired, TypedDict
from langgraph.graph import END, START, StateGraph

class State(TypedDict):
    text: str
    words: NotRequired[int]      # NotRequired: lo scrive un nodo, all'inizio non c'è
    verdict: NotRequired[str]

def count(state: State) -> dict:
    return {"words": len(state["text"].split())}   # restituisce solo i campi che cambia

def short(state: State) -> dict:
    return {"verdict": "breve"}

def long(state: State) -> dict:
    return {"verdict": "lunga"}

def route(state: State) -> str:
    return "SHORT" if state["words"] < 5 else "LONG"

builder = StateGraph(State)
builder.add_node("count", count)
builder.add_node("short", short)
builder.add_node("long", long)
builder.add_edge(START, "count")
builder.add_conditional_edges("count", route, {"SHORT": "short", "LONG": "long"})
builder.add_edge("short", END)
builder.add_edge("long", END)
graph = builder.compile()

graph.invoke({"text": "studio e palestra"})
# {'text': 'studio e palestra', 'words': 3, 'verdict': 'breve'}
```

- Lo **stato** è un `TypedDict`: un dizionario con le chiavi dichiarate.
- Un **nodo** riceve lo stato e restituisce **solo le chiavi che cambia**; LangGraph le
  unisce allo stato.
- `START` ed `END` sono l'inizio e la fine; `compile()` rende il grafo eseguibile e rifiuta
  un arco verso un nodo che non esiste (`ValueError: Found edge ending at unknown node`).
  Attenzione: un nodo aggiunto ma **mai raggiunto** da un arco viene accettato senza errori.
  Si scopre disegnando il grafo, o con un test che passa da quel nodo.
- Un **arco condizionale** chiama una funzione che sceglie un'etichetta; la **mappa
  esplicita** (`{"SHORT": "short", ...}`) dice a LangGraph in anticipo tutte le destinazioni
  possibili, così le controlla e le disegna.

`graph.get_graph().draw_mermaid()` restituisce il grafo come diagramma Mermaid, lo stesso
formato del README: l'arco condizionale compare tratteggiato, con le sue etichette.

### Le pause: `interrupt`, il checkpointer e `Command(resume=...)`

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool

def ask(state: AskState) -> dict:
    answer = interrupt({"question": f"Va bene il piano '{state['plan']}'?"},
                       response_schema=Answer)
    return {"approved": answer.ok}

graph = builder.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "giorno-1"}}

graph.invoke({"plan": "studio 9-11"}, config)       # si ferma: result["__interrupt__"]
graph.get_state(config).next                         # ('ask',): aspetta in quel nodo
graph.invoke(Command(resume={"ok": True}), config)   # riprende: {'plan': ..., 'approved': True}
```

- `interrupt(valore)` **ferma il grafo**. Chi ha chiamato `invoke` trova il valore in
  `result["__interrupt__"]`: è la domanda da mostrare all'utente.
- Per fermarsi e riprendere serve un **checkpointer**, che salva lo stato a ogni passo, e un
  **`thread_id`**, che identifica la conversazione: due pianificazioni diverse hanno due
  `thread_id` e non si mescolano.
- `Command(resume=risposta)` riprende il grafo; dentro il nodo, `interrupt(...)` restituisce
  la risposta.
- Con **`response_schema`** la risposta è validata da Pydantic: una risposta sbagliata
  (`{"ok": "forse"}`) solleva `ValidationError` e il grafo **resta in pausa** nello stesso
  nodo, pronto per un nuovo tentativo.
- `get_state(config)` è la "fotografia" del thread: `.values` è lo stato, `.next` i nodi che
  aspettano; `get_state_history(config)` elenca tutti i checkpoint salvati, dal più recente.

### Il contesto di un'esecuzione: il config

```python
from langchain_core.runnables import RunnableConfig

def greet(state: State, config: RunnableConfig) -> dict:
    language = config.get("configurable", {}).get("language", "it")
    return {"verdict": "ciao" if language == "it" else "hello"}

graph.invoke({"text": "x"}, {"configurable": {"language": "en"}})   # verdict: 'hello'
```

Un nodo che dichiara un secondo parametro `config` riceve il config dell'esecuzione: oltre
al `thread_id` ci si può mettere quello che riguarda **questa richiesta e non il piano**,
come la lingua dei messaggi. Ogni `invoke` porta il suo.

### Cosa mettere nello stato, e cosa no

Lo stato viene salvato dal checkpointer, quindi deve essere fatto di dati **serializzabili**:
testi, numeri, liste, dizionari, modelli Pydantic dichiarati. Un client LLM o una connessione
al database **non** vanno nello stato: nel progetto `build_graph` li riceve come parametri e i
nodi li vedono con una *closure* (sono funzioni definite dentro `build_graph`). Nei test e
nell'API LangGraph gira in modalità *strict* (`LANGGRAPH_STRICT_MSGPACK=true`): accetta solo i
tipi dichiarati in `PlannerState`, così un tipo sbagliato si scopre subito.

## Il grafo del progetto

Il diagramma completo è nel [README](../../README.md#how-it-works). I pezzi, con i concetti
di questo capitolo:

| Nodo | Cosa fa | Concetto |
|---|---|---|
| `parser` | l'LLM legge la frase e scrive i task | nodo con LLM |
| `check_saved_day` | se la data ha già un piano, ne unisce i task | nodo con database, solo con un archivio |
| `ask_approval` | mostra i task e aspetta le correzioni | `interrupt` con `response_schema` |
| `editor` | applica le correzioni | nodo puro Python |
| `scheduler` | CP-SAT costruisce l'orario ([capitolo 4](04-ortools-cpsat.md)) | arco condizionale dopo: fine, revisione o conflitto |
| `review_plan`, `resolve_conflict` | chiedono all'utente se qualcosa non entra o si scontra | cicli: si torna a `ask_approval` o a `editor` |
| `critic` | l'LLM valuta la giornata | nodo con LLM, **senza** interrupt |
| `suggest_activities` | mostra le proposte del Critico | `interrupt` |
| `save_plan` | salva nel database | l'unico che scrive fuori dal grafo |
| `extract_preferences`, `confirm_preferences`, `store_preferences` | la memoria delle preferenze | LLM, poi `interrupt`, poi database |

## Dove guardare nel codice

- [agents/graph.py](../../src/planner/agents/graph.py): `build_graph` con tutti i nodi, le
  funzioni di instradamento (`route_after_schedule`…) e le mappe degli archi; `language_of`
  legge la lingua dal config.
- [agents/state.py](../../src/planner/agents/state.py): `PlannerState`, con un commento per
  ogni chiave su chi la scrive.
- [agents/approval.py](../../src/planner/agents/approval.py) ed
  [agents/editor.py](../../src/planner/agents/editor.py): i valori delle domande (dati JSON
  semplici, leggibili da qualunque client) e i modelli delle risposte.
- [llm/langchain_client.py](../../src/planner/llm/langchain_client.py): il client LangChain,
  con un `ChatOllama` per schema creato una volta sola.
- [api/app.py](../../src/planner/api/app.py): `resume_plan` riprende il grafo con
  `Command(resume=...)` dopo aver guardato `get_state` (404 se il thread non c'è, 409 se è finito).
- [tests/unit/test_graph.py](../../tests/unit/test_graph.py): il grafo provato con un LLM finto,
  pausa per pausa.

## Trappole incontrate

### Il nodo ripreso ricomincia dall'inizio

**Sintomo:** nell'esempio con `interrupt`, una riga stampata all'inizio del nodo `ask`
compare **a ogni ripresa**: alla prima esecuzione, dopo la risposta sbagliata e dopo quella
giusta.
**Causa:** quando il grafo riprende, LangGraph non continua dall'istruzione dopo
`interrupt`: **riesegue il nodo da capo**, e questa volta `interrupt` restituisce la risposta.
**Conseguenza nel progetto:** un nodo con `interrupt` non deve fare niente di costoso o con
effetti prima della domanda. Per questo il Critico (chiamata all'LLM, lenta e non sempre
uguale) è nel nodo `critic`, e la domanda sulle proposte è in un nodo separato,
`suggest_activities`; lo stesso per l'estrazione delle preferenze e la loro conferma. Un
test controlla che alla ripresa l'LLM non venga chiamato di nuovo.

### `Command(resume={})` non riprende

**Sintomo:** una risposta "vuota" (`{}`, cioè "nessuna correzione") lasciava il grafo fermo
alla stessa domanda.
**Causa:** un dizionario passato a `resume` viene letto come una mappa *id della domanda →
risposta*; vuoto, vuol dire "nessuna risposta per nessuna domanda". Peggio: dopo una
risposta rifiutata, `{}` **ripresenta quella vecchia** e il suo errore.
**Correzione:** ogni risposta ha sempre almeno un campo (`{"edits": {}}`, `{"accepted": []}`),
e l'API rifiuta un `answer` vuoto prima di arrivare al grafo.

### Riprendere un grafo finito non dà errore

**Sintomo:** rimandando una risposta dopo la fine, il grafo restituiva di nuovo lo stato
finale, in silenzio.
**Correzione:** prima di riprendere, l'API guarda `get_state(config).next`: se è vuoto, il
piano è finito e risponde 409.

### La lingua nello stato: due valori nello stesso passo

**Sintomo:** salvando la lingua nello stato a ogni risposta
(`Command(resume=..., update={"language": ...})`), il nuovo tentativo dopo una risposta
rifiutata falliva con `InvalidUpdateError`.
**Causa:** la risposta rifiutata aveva già scritto la lingua in quel passo; il tentativo la
scriveva una seconda volta, e un canale dello stato accetta **un solo valore per passo**.
**Correzione:** la lingua non è un dato del piano ma il contesto della richiesta: viaggia nel
**config** (`{"configurable": {"thread_id": ..., "language": ...}}`), e ogni richiesta porta
la sua.

### Senza istruzioni, il modello cambia lingua

**Sintomo:** provando `llm.batch(...)` con solo un messaggio utente ("umore di: vacanza"),
qwen ha risposto **in cinese**.
**Lezione:** un modello addestrato su molte lingue, senza un prompt di sistema, sceglie da
solo. Nel progetto ogni chiamata ha un prompt di sistema in italiano, e la lingua delle
risposte per l'utente è chiesta esplicitamente ([capitolo 2](02-ollama-llm.md)).

## Prova tu

Gli esempi si eseguono dalla cartella del progetto, con `python`.

1. **Il grafo minimo.** Copia l'esempio di "Lo stato, i nodi, gli archi" e invocalo con due
   frasi, una corta e una lunga. Poi stampa `graph.get_graph().draw_mermaid()` e incolla il
   risultato su <https://mermaid.live>. *Verifica:* la frase corta finisce in `short`, quella
   lunga in `long`; nel disegno l'arco condizionale è tratteggiato con le etichette
   `SHORT` e `LONG`.
2. **Il nodo che ricomincia.** Nell'esempio con `interrupt` aggiungi `print("nodo ask")`
   come prima riga di `ask`, poi invoca, riprendi con `{"ok": "forse"}` (catturando
   `ValidationError`) e infine con `{"ok": True}`. *Verifica:* la riga compare tre volte; dopo
   la risposta sbagliata `get_state(config).next` è ancora `('ask',)`.
3. **Il grafo del progetto, a mano.**

   ```python
   import json
   from langgraph.checkpoint.memory import InMemorySaver
   from langgraph.types import Command
   from planner.agents.graph import build_graph
   from planner.solver.models import DayConfig
   from tests.fakes import FakeClient

   parser = json.dumps({"tasks": [{"source": "studio", "title": "Studio", "duration_min": 60}]})
   critic = json.dumps({"assessment": "Giornata equilibrata.", "too_empty": False, "suggestions": []})
   graph = build_graph(FakeClient([parser, critic]), checkpointer=InMemorySaver())
   config = {"configurable": {"thread_id": "prova"}}

   result = graph.invoke({"user_input": "studio", "day": DayConfig()}, config)
   print(result["__interrupt__"][0].value["step"], graph.get_state(config).next)
   final = graph.invoke(Command(resume={"edits": {"t1": {"fixed_start": "10:00"}}}), config)
   print([(s.title, s.start_min) for s in final["schedule"].scheduled])
   ```

   *Verifica:* la prima riga stampa `confirm_tasks ('ask_approval',)`; la seconda
   `[('Studio', 600)]`, cioè lo studio alle 10:00 come chiesto nella correzione.
   `len(list(graph.get_state_history(config)))` conta i checkpoint salvati lungo il percorso.
4. **La risposta vuota.** Nello stesso esempio, al posto di `{"edits": {...}}` riprendi con
   `Command(resume={})`. *Verifica:* il risultato contiene di nuovo `__interrupt__` e `next`
   è ancora `('ask_approval',)`: il grafo non è ripartito.
5. **LangChain al posto del client diretto.** Metti `LLM_PROVIDER=langchain_ollama` in `.env`,
   avvia l'API e pianifica una giornata. *Verifica:* funziona allo stesso modo; il client
   cambia, ma validazione e correzione sono le stesse (`LLMClient`). Rimetti `ollama` alla fine.
6. **Un test che deve fallire.** In [graph.py](../../src/planner/agents/graph.py), in
   `route_after_schedule`, sostituisci `return REVIEW` con `return DONE` ed esegui
   `python -m pytest tests/unit/test_graph.py`. *Verifica:* falliscono 8 test, tutti quelli
   che passano dalla revisione del piano. Rimetti `REVIEW`.

## Per approfondire

- LangGraph: <https://langchain-ai.github.io/langgraph/>, in particolare *Graph API*
  (stato, nodi, archi), *Persistence* (checkpointer e thread) e *Human-in-the-loop*
  (`interrupt` e `Command`). Controlla che la documentazione sia della versione 1.x.
- LangChain: <https://python.langchain.com/>, le pagine *Chat models*, *Runnable interface* e
  *Structured output*; per Ollama, l'integrazione `langchain-ollama`.
- Prossimo capitolo: [OR-Tools CP-SAT](04-ortools-cpsat.md), il solver che il nodo `scheduler`
  chiama per costruire l'orario.
