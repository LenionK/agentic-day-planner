# 1. Pydantic

> Versione nel progetto: **pydantic 2.14.1** (più `pydantic-settings` per la configurazione).

## Cos'è

In Python i type hint (`duration_min: int`) sono solo indicazioni: nessuno ti impedisce di
mettere `-5` o `"tre"` in una variabile dichiarata `int`. **Pydantic** li trasforma in
controlli veri. Descrivi i dati con una classe, e Pydantic:

- **controlla** ogni valore quando crei un oggetto, e se qualcosa non va solleva un
  `ValidationError` che dice quale campo è sbagliato e perché;
- **converte** quando ha senso: la stringa `"45"` diventa l'intero `45`;
- **traduce** l'oggetto in dizionario o JSON e viceversa;
- **descrive** la classe come *JSON Schema*, un formato standard che altri programmi (anche
  un LLM) possono leggere.

## Perché qui

Nel progetto i dati arrivano da fonti di cui non ci si può fidare:

- **un LLM**, che può scrivere una durata negativa o un orario inventato;
- **l'utente**, che può scrivere un orario nel formato sbagliato;
- **il database**, da cui si rileggono le giornate salvate.

Pydantic è il confine: qualunque cosa entri passa da un modello, e da lì in poi il resto del
codice può fidarsi dei dati. Il solver, per esempio, non controlla mai se una durata è
positiva: se esiste un `Task`, la durata è positiva per costruzione.

C'è un secondo motivo, più specifico: lo stesso modello che convalida la risposta dell'LLM
gli spiega anche *come* rispondere, tramite il suo JSON Schema (vedi il
[capitolo 2](02-ollama-llm.md)).

## Concetti chiave

### Il modello: una classe con i campi tipizzati

```python
from pydantic import BaseModel, Field

class Task(BaseModel):
    id: str
    title: str = Field(min_length=1)
    required: bool = False                              # valore di default
    duration_min: int = Field(gt=0, le=720)             # > 0 e <= 720
    priority: int = Field(default=3, ge=1, le=5)        # tra 1 e 5, di default 3
    deadline_min: int | None = Field(default=None, ge=0, le=1440)  # facoltativo
```

- Un campo **senza default** è obbligatorio (`id`, `title`, `duration_min`).
- `int | None = None` significa "un intero oppure niente": il campo è facoltativo.
- `Field(...)` aggiunge vincoli: `gt` (maggiore di), `ge` (maggiore o uguale), `le`, `lt`,
  `min_length`, `max_length` per stringhe e liste.

### La validazione e i suoi errori

```python
Task(id="t1", title="Report", duration_min=0)
```
```
1 validation error for Task
duration_min
  Input should be greater than 0 [type=greater_than, input_value=0, input_type=int]
```

L'errore dice il campo (`duration_min`), la regola violata e il valore ricevuto. Con
`err.errors()` ottieni la stessa informazione come lista di dizionari, comoda da mostrare
all'utente o da rimandare all'LLM.

### La conversione (modalità "lax")

```python
Task(id="t1", title="x", duration_min="45", required="true")
# Task(id='t1', title='x', required=True, duration_min=45, ...)
```

Pydantic converte i valori che hanno un'interpretazione ovvia (`"45"` → `45`,
`"true"` → `True`). Se l'interpretazione non c'è, è un errore:
`duration_min="tre quarti d'ora"` dà *"Input should be a valid integer"*.

### I validator: regole che coinvolgono più campi

I vincoli di `Field` guardano un campo alla volta. Per una regola come "la finestra di tempo
deve contenere la durata" serve un `model_validator`, che gira dopo aver controllato i campi
singoli e vede l'oggetto intero:

```python
from pydantic import model_validator

class Task(BaseModel):
    ...
    @model_validator(mode="after")
    def check_window(self) -> "Task":
        if self.earliest_start_min is not None and self.deadline_min is not None:
            if self.deadline_min - self.earliest_start_min < self.duration_min:
                raise ValueError("time window is shorter than the task duration")
        return self
```

Un `ValueError` sollevato dentro un validator diventa un `ValidationError` come gli altri.
Per controllare un solo campo con una regola tua c'è `field_validator`: nel progetto
controlla che gli orari scritti dall'utente siano `"HH:MM"`.

### Dentro e fuori: `model_validate`, `model_dump`, `model_copy`

| Metodo | Cosa fa | Valida? |
|---|---|---|
| `Task(**campi)` / `Task.model_validate(dizionario)` | crea l'oggetto da dati | **sì** |
| `Task.model_validate_json(testo)` | crea l'oggetto da una stringa JSON | **sì** |
| `task.model_dump()` | oggetto → dizionario | — |
| `task.model_dump(exclude_unset=True)` | solo i campi impostati esplicitamente | — |
| `task.model_copy(update={...})` | copia con alcuni campi cambiati | **no!** |

L'ultima riga è importante: vedi le trappole.

### `exclude_unset`: "non detto" non è "detto: niente"

Per una correzione dell'utente servono tre casi diversi per l'orario di inizio:
non toccarlo, cambiarlo, toglierlo. Con `None` come default, "non toccarlo" e "toglierlo"
sembrano uguali. Pydantic però ricorda quali campi sono stati scritti:

```python
TaskEdit().model_dump(exclude_unset=True)                  # {}  -> non toccare niente
TaskEdit(fixed_start=None).model_dump(exclude_unset=True)  # {'fixed_start': None} -> togli l'orario
TaskEdit().model_dump()                                    # tutti i campi a None: informazione persa
```

### `extra="forbid"`: un campo sconosciuto è un errore

Di default Pydantic **ignora** i campi che non conosce. Per un modello che riceve
correzioni è pericoloso: un errore di battitura farebbe sparire la correzione senza
avvisare. Con `ConfigDict(extra="forbid")` diventa un errore:

```python
from pydantic import ConfigDict

class TaskEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: int | None = Field(default=None, ge=1, le=5)

TaskEdit(priorty=2)
# priorty
#   Extra inputs are not permitted [type=extra_forbidden, ...]
```

### Il JSON Schema

```python
TaskDraft.model_json_schema()
```

restituisce la descrizione della classe: i campi **nell'ordine in cui sono scritti**, il
tipo di ognuno, i vincoli (`"exclusiveMinimum": 0, "maximum": 720`) e la lista dei campi
obbligatori. È quello che il progetto passa all'LLM per vincolarne la risposta.

### pydantic-settings: la configurazione da `.env`

`BaseSettings` è un modello che si riempie da solo leggendo le variabili d'ambiente e il
file `.env`: `LLM_MODEL=qwen2.5:7b` nel file diventa `Settings().llm_model`. I valori
vengono validati come in ogni altro modello, e `SecretStr` evita che una chiave API finisca
stampata nei log.

## Dove guardare nel codice

- [solver/models.py](../../src/planner/solver/models.py): i modelli del dominio. `Task`,
  `DayConfig`, `Interval` e i loro `model_validator`; `Schedule` è il risultato del solver.
- [agents/parser.py:30-48](../../src/planner/agents/parser.py#L30-L48): `TaskDraft`, il
  task come lo scrive l'LLM (orari come stringhe `"HH:MM"`), separato da `Task` (orari in
  minuti). Due modelli per due confini diversi.
- [agents/editor.py](../../src/planner/agents/editor.py): `TaskEdit` con `extra="forbid"` e
  un `field_validator` sugli orari; `apply_edits` usa `exclude_unset` e `model_validate`.
- [llm/base.py:19](../../src/planner/llm/base.py#L19): `model_validate_json` sulla risposta
  grezza dell'LLM.
- [agents/graph.py:146-148](../../src/planner/agents/graph.py#L146-L148): la risposta
  dell'utente al grafo è validata con un modello (`response_schema`), poi salvata nello
  stato come dizionario semplice.
- [config.py](../../src/planner/config.py): `Settings` con pydantic-settings.

## Trappole incontrate

### `model_copy` non valida

**Il pericolo:** scrivendo l'editor delle correzioni, il modo più naturale per applicare una
modifica sembrava `task.model_copy(update=modifiche)`. Ma una correzione con una durata più
lunga della finestra di tempo sarebbe passata, e il solver avrebbe ricevuto un task impossibile.
**Causa:** `model_copy(update=...)` copia l'oggetto e sostituisce i campi **senza far girare
nessun controllo**, neanche i validator:

```python
task.model_copy(update={"duration_min": -5}).duration_min   # -5, nessun errore
Task.model_validate({**task.model_dump(), "duration_min": -5})  # ValidationError
```

**Correzione:** quando i nuovi valori vengono da fuori, si ricostruisce l'oggetto con
`model_validate` ([editor.py:89-90](../../src/planner/agents/editor.py#L89-L90)).
`model_copy` resta dove i valori sono già sicuri per costruzione: in
[merge.py](../../src/planner/agents/merge.py) i task salvati vengono fissati agli orari che
avevano già superato tutti i controlli, e un commento lo spiega.

### Un `None` che voleva dire due cose

**Il problema:** con un normale `model_dump()` non ci sarebbe stato modo di togliere un
orario a un task: "lascia com'è" e "togli" sarebbero arrivati entrambi come `None`.
**Correzione:** `model_dump(exclude_unset=True)`, che tiene solo i campi scritti
davvero ([editor.py:84](../../src/planner/agents/editor.py#L84)).

### L'orario nel formato sbagliato, fermato al confine

**Sintomo:** dopo aver modificato un orario nell'interfaccia compariva
*"invalid time format: '17:00:00.000', expected 'HH:MM'"*.
**Causa:** la tabella di Streamlit restituisce gli orari modificati come stringhe ISO
(dettagli nel [capitolo 5](05-streamlit.md)).
**Perché è una buona notizia:** il `field_validator` di `TaskEdit` ha fatto il suo lavoro.
Il dato sbagliato si è fermato al confine con un messaggio chiaro, invece di diventare un
orario strano nel piano. La correzione è stata convertire il formato nell'interfaccia, non
allentare il controllo.

## Prova tu

Apri un terminale nella cartella del progetto ed esegui `python`, poi importa i modelli:

```python
from pydantic import ValidationError
from planner.solver.models import Task
from planner.agents.editor import TaskEdit
from planner.agents.parser import TaskDraft
```

1. **Leggi un errore.** Crea un `Task` con `priority=7`. *Verifica:* l'errore nomina il
   campo `priority` e dice che il valore deve essere minore o uguale a 5.
2. **Un validator tra più campi.** Crea un task di 60 minuti con `earliest_start_min=600` e
   `deadline_min=630`. *Verifica:* l'errore è *"time window is shorter than the task
   duration"* e non nomina un campo singolo: riguarda il modello intero.
3. **La differenza tra copia e validazione.** Crea un task valido, poi prova a portare la
   durata a `-5` prima con `model_copy` e poi con `model_validate`. *Verifica:* il primo
   modo restituisce un task con durata `-5`, il secondo solleva un errore.
4. **I tre stati di un campo.** Confronta `TaskEdit().model_dump(exclude_unset=True)`,
   `TaskEdit(deadline=None).model_dump(exclude_unset=True)` e
   `TaskEdit(deadline="18:00").model_dump(exclude_unset=True)`. *Verifica:* ottieni tre
   risultati diversi; il primo è un dizionario vuoto.
5. **Lo schema che vede l'LLM.** Esegui `import json` e
   `print(json.dumps(TaskDraft.model_json_schema(), indent=2))`. *Verifica:* `source` è il
   primo campo di `properties`, e `required` contiene solo i campi senza default.
6. **Un test che deve fallire.** In [editor.py](../../src/planner/agents/editor.py) togli
   temporaneamente la riga `model_config = ConfigDict(extra="forbid")` da `TaskEdit` ed esegui
   `python -m pytest tests/unit/test_editor.py`. *Verifica:* almeno un test fallisce,
   perché un campo scritto male ora viene ignorato invece di essere rifiutato. Rimetti la riga
   e controlla che i test tornino verdi.

## Per approfondire

- Documentazione ufficiale: <https://docs.pydantic.dev/2.14/>, in particolare le pagine
  *Models*, *Fields*, *Validators* e *JSON Schema*.
- pydantic-settings: <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>
- Ogni messaggio di errore contiene un link (`https://errors.pydantic.dev/...`) che spiega
  quel tipo di errore.
- Prossimo capitolo: [Ollama e LLM locali](02-ollama-llm.md), dove lo schema di Pydantic
  diventa il formato della risposta del modello.
