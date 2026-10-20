# 2. Ollama e LLM locali

> Versioni nel progetto: libreria Python **ollama 0.6.3**, modello **qwen2.5:7b** (circa
> 4,7 GB). LangChain (`langchain-ollama`) è disponibile come alternativa intercambiabile.

## Cos'è

Un **LLM** (*Large Language Model*) è un modello che, dato un testo, genera il seguito un
pezzo alla volta. I pezzi si chiamano *token* (una parola corta, o un frammento di parola
lunga). Ogni token è scelto guardando tutto quello che c'è prima, compreso quello che il
modello ha appena scritto. Questo dettaglio tornerà utile più avanti.

**Ollama** è un programma che fa girare gli LLM sul tuo computer. Scarica i modelli, li
carica in memoria (sulla scheda video se c'è) e li espone come un piccolo server web su
`http://localhost:11434`. Il tuo programma gli manda una richiesta e riceve la risposta,
come con un servizio online, ma **niente esce dal tuo PC** e non si paga niente.

Comandi essenziali:

```
ollama pull qwen2.5:7b      scarica un modello
ollama list                 i modelli scaricati
ollama run qwen2.5:7b       chat da terminale, per provare a mano
ollama ps                   i modelli caricati in memoria in questo momento
```

## Perché qui

- **Local-first:** la descrizione della giornata è un dato personale. Con un modello locale
  resta sul PC, e il progetto funziona senza account né costi.
- **Un modello piccolo è una buona scuola.** Un modello da 7 miliardi di parametri sbaglia
  più spesso di uno grande. Questo costringe a costruire intorno all'LLM i controlli che
  servirebbero comunque: validare, verificare sul testo dell'utente, misurare. Molte
  scelte del progetto nascono da errori veri del modello (vedi le trappole).
- **L'LLM fa solo quello che sa fare.** Capisce il linguaggio naturale: "se riesco una corsa
  dopo le 20" diventa un task facoltativo che inizia dopo le 20:00. Non fa i conti e non
  costruisce l'orario: quello lo fa il solver ([capitolo 4](04-ortools-cpsat.md)), che non
  sbaglia le addizioni.

## Concetti chiave

### I messaggi: system, user, assistant

Un modello "chat" riceve una lista di messaggi, ciascuno con un ruolo:

```python
messages = [
    {"role": "system", "content": "Estrai i task dalla frase dell'utente. ..."},  # le istruzioni
    {"role": "user", "content": "domani dentista alle 15 e palestra"},  # l'input
]
```

- **system**: le istruzioni fisse del compito (il *prompt*).
- **user**: il testo da elaborare.
- **assistant**: le risposte del modello. Rimetterle nella lista serve a continuare una
  conversazione, ed è così che il progetto chiede al modello di correggersi.

### Le opzioni di generazione

| Opzione | Cosa controlla | Nel progetto |
|---|---|---|
| `temperature` | quanto è casuale la scelta dei token: 0 = sempre il più probabile | `0.0`: vogliamo risposte ripetibili, non creative |
| `num_ctx` | quanti token il modello può leggere in tutto (prompt + risposta) | `8192`: impostato esplicitamente, per non dipendere dal default di Ollama |
| `num_predict` | quanti token può generare al massimo | `2048`: un tetto contro risposte che non finiscono |

Si scelgono in `.env` (`LLM_TEMPERATURE`, `LLM_NUM_CTX`, ...) e arrivano a Ollama da
[ollama_client.py](../../src/planner/llm/ollama_client.py).

### L'output strutturato: il modello risponde con il *tuo* schema

Un LLM scrive testo libero, ma un programma ha bisogno di dati. Ollama accetta un parametro
`format` con un **JSON Schema**, e lo usa per **vincolare la generazione**: a ogni passo
scarta i token che renderebbero il JSON non conforme. La risposta ha quindi sempre le chiavi
e i tipi giusti. Lo schema lo produce Pydantic ([capitolo 1](01-pydantic.md)):

```python
from ollama import Client

response = Client(host="http://localhost:11434").chat(
    model="qwen2.5:7b",
    messages=messages,
    format=ParsedDay.model_json_schema(),  # lo schema della risposta
    options={"temperature": 0.0},
)
parsed = ParsedDay.model_validate_json(response.message.content)  # e poi si valida comunque
```

Perché validare se la generazione è già vincolata? Perché il vincolo garantisce la
**forma**, ma non tutti i vincoli dello schema e soprattutto non il **contenuto**. Una
durata può rispettare il tipo `int` ed essere comunque sbagliata o inventata.

### L'ordine dei campi è l'ordine in cui il modello "pensa"

Il modello genera i campi nell'ordine dello schema, e ogni token dipende da quelli già
scritti. Quindi un campo scritto **prima** influenza quelli **dopo**. Il progetto lo
sfrutta di proposito:

- in `TaskDraft` il primo campo è `source`: il modello copia il pezzo di frase che
  riguarda il task, e *solo dopo* decide durata e orari, guardando quel pezzo;
- in `CriticReview` il campo `assessment` (la descrizione della giornata) viene prima di
  `too_empty` (la decisione): prima il ragionamento, poi la conclusione;
- in `SameVerdict` `reasoning` viene prima di `same`, per la stessa ragione.

Se metti la decisione per prima, il modello decide "a istinto" e poi scrive un ragionamento
che la giustifica.

### Il ciclo di correzione

Se la risposta non passa la validazione, il progetto non si arrende subito. Rimanda al
modello la sua risposta e l'errore di Pydantic, e gli chiede di correggersi
([base.py](../../src/planner/llm/base.py)):

```python
for attempt in range(self.max_retries + 1):
    raw = self._complete(history, schema)
    try:
        return schema.model_validate_json(raw)
    except ValidationError as err:
        if attempt == self.max_retries:
            raise
        history.append({"role": "assistant", "content": raw})
        history.append({"role": "user", "content": f"La risposta non è valida:\n{err}\n..."})
```

### Un'interfaccia, più implementazioni

Il resto del programma non sa se dietro c'è Ollama o LangChain: conosce solo `LLMClient`,
una classe astratta con un metodo `generate(messages, schema)`. Le implementazioni
riempiono solo `_complete` (manda i messaggi, restituisci il testo); validazione e
correzione stanno una volta sola nella classe base. Una *factory* sceglie l'implementazione
leggendo `LLM_PROVIDER` da `.env`.

Il vantaggio più grande si vede nei test: `FakeClient` è un `LLMClient` che restituisce
risposte scritte a mano. Così i test del grafo girano in un secondo, senza Ollama, e danno
sempre lo stesso risultato ([capitolo 9](09-test-e-valutazione.md)).

### Scrivere un prompt

I prompt del progetto seguono alcune regole, imparate a forza di errori:

- **In italiano**, come l'input dell'utente.
- **"Rispondi solo con il JSON richiesto."**
- **Un campo alla volta, nell'ordine dello schema**, con la regola per ciascuno e i casi
  limite espliciti ("*Devo* da solo NON rende il task obbligatorio").
- **Pochi esempi brevi**, compresi quelli negativi ("Frase: 'cena da Luca alle 20 e
  bucato' → Preferenze: nessuna").
- **I fatti li calcola Python.** Minuti liberi, ore occupate e intervallo più lungo
  arrivano al Critico già calcolati. Il modello li usa, non li ricava.

### Il modello propone, Python verifica, l'utente conferma

Nessuna risposta dell'LLM viene usata così com'è. Ci sono tre livelli:

1. **Pydantic** controlla forma e vincoli.
2. **Controlli sul testo dell'utente**: un orario la cui ora non compare nella frase è
   inventato, e viene tolto con un avviso. Una preferenza il cui `source` non è nella frase
   viene scartata.
3. **L'utente** vede e conferma i task prima della pianificazione, e le preferenze prima di
   salvarle.

## Dove guardare nel codice

- [llm/base.py](../../src/planner/llm/base.py): `LLMClient`, con la validazione e il ciclo
  di correzione.
- [llm/ollama_client.py](../../src/planner/llm/ollama_client.py): la chiamata a Ollama con
  `format=schema.model_json_schema()`.
- [llm/langchain_client.py](../../src/planner/llm/langchain_client.py): la stessa cosa con
  `ChatOllama` di LangChain.
- [llm/factory.py](../../src/planner/llm/factory.py) e
  [config.py](../../src/planner/config.py): la scelta del client da `.env`.
- [agents/parser.py](../../src/planner/agents/parser.py): il prompt più importante
  (`SYSTEM_PROMPT`), e `clean_times`, che toglie gli orari inventati.
- [agents/critic.py](../../src/planner/agents/critic.py): un prompt che riceve fatti già
  calcolati (`day_facts`).
- [agents/preferences.py](../../src/planner/agents/preferences.py): due compiti per l'LLM
  (estrarre preferenze e giudicare se due preferenze sono uguali) e i controlli sulle
  risposte.

## Trappole incontrate

### Orari inventati, o spostati sul task sbagliato

**Sintomo:** il modello assegnava a volte un orario a un task che non ne aveva, inventando
un'ora mai nominata oppure copiando quella di un altro task della stessa frase.
L'esercizio 4 di *Prova tu* ne mostra un caso reale.
**Correzione:** il campo `source` come primo campo (il modello isola il pezzo di frase del
task prima di decidere gli orari) e `clean_times`, che controlla in Python ogni orario.
Se l'ora non compare nella frase, l'orario viene tolto. Se compare solo nel `source` di un
altro task, viene tolto anche quello. Ogni rimozione produce un avviso visibile all'utente.

### "La giornata è molto intensa" con una sola riunione

**Sintomo:** con "domani ho una riunione alle 10", il Critico rispondeva che la giornata era
molto intensa.
**Causa:** al modello arrivava la lista degli intervalli liberi, e doveva ricavarne da solo
quanto fosse piena la giornata. Un modello da 7B sbaglia questi conti.
**Correzione:** `day_facts` calcola in Python minuti occupati, minuti liberi, percentuale e
intervallo più lungo, e il prompt li riporta esplicitamente. Regola generale: **all'LLM i
giudizi, a Python i numeri**.

### Preferenze scritte in inglese

**Sintomo:** il modello scriveva a volte il testo delle preferenze in inglese, anche con
frasi in italiano. Il confronto con le preferenze salvate in italiano dava similarità basse, e
le contraddizioni non venivano più trovate ([capitolo 8](08-embedding-pgvector.md)).
**Correzione:** il prompt chiede esplicitamente italiano, terza persona, e di iniziare con
un verbo ("preferisce", "evita"...). A volte il modello lascia ancora piccoli errori, come
"preferenceisce": per questo l'utente conferma il testo prima che venga salvato.

### Impegni scambiati per preferenze

**Sintomo:** impegni di quel giorno, come un appuntamento a un orario preciso, venivano
estratti come preferenze, che sarebbero poi valse per tutti i giorni futuri.
**Correzione:** un campo `cue` prima di `text`. Il modello deve copiare dalla frase le
parole che rendono la frase una preferenza ("sempre", "mi concentro meglio"), e Python
controlla che ci siano davvero. Se il modello non sa indicare un indizio, di solito sta
guardando un impegno. In più, il prompt ha esempi negativi.

### Un JSON valido non è una risposta giusta

Un esperimento che puoi ripetere (vedi *Prova tu*). Con lo schema
`Mood(reasoning: str, mood: Literal["positivo", "neutro", "negativo"])` e la frase "domani
ho tre esami e poi il dentista", lo stesso programma, eseguito due volte con
`temperature=0`, ha risposto così:

```
reasoning='... con esami accademici e un appuntamento al dentista ... potrebbe essere vista come stressante.', mood='positivo'
reasoning='... con esami accademici e un appuntamento al dentista, che potrebbero causare stress.', mood='negativo'
```

Le due lezioni:

1. **Entrambe le risposte sono valide per Pydantic**, ma la prima si contraddice da sola.
   La validazione controlla la forma, non il senso.
2. **Temperatura 0 non vuol dire risultati identici.** Riduce molto la variabilità ma non la
   elimina. Per esempio, piccole differenze numeriche nei calcoli sulla scheda video
   possono cambiare un token, e da lì il resto della risposta. Per questo la qualità di un prompt si **misura** su molti
   casi, più volte, e non si giudica da una prova sola.

### Misurare con gli esempi del prompt è barare

Gli esempi scritti nel prompt il modello li "conosce", quindi usarli come casi di test dà un
risultato troppo ottimista. Gli script di valutazione usano frasi diverse, divise in un
insieme di sviluppo (per migliorare il prompt) e uno tenuto da parte (per la misura finale).
Ne parla il [capitolo 9](09-test-e-valutazione.md).

## Prova tu

Servono Ollama acceso e `qwen2.5:7b` scaricato (`ollama list` per controllare).

1. **Parla con il modello a mano.** Esegui `ollama run qwen2.5:7b` e scrivi "estrai i task
   da: domani dentista alle 15 e palestra". Esci con `/bye`. *Verifica:* la risposta è testo
   libero, ogni volta in una forma diversa. È il motivo per cui serve l'output strutturato.
2. **Output strutturato dal progetto.** Salva questo script in un file fuori dalla cartella
   `src` ed eseguilo con `python`:

   ```python
   from typing import Literal

   from pydantic import BaseModel

   from planner.config import Settings
   from planner.llm.factory import build_llm_client


   class Mood(BaseModel):
       reasoning: str
       mood: Literal["positivo", "neutro", "negativo"]


   client = build_llm_client(Settings())
   messages = [
       {
           "role": "system",
           "content": "Valuta l'umore della frase. Rispondi solo con il JSON richiesto.",
       },
       {"role": "user", "content": "domani ho tre esami e poi il dentista"},
   ]
   print(repr(client.generate(messages, Mood)))
   ```

   *Verifica:* ottieni un oggetto `Mood`, non una stringa, e `mood` è sempre uno dei tre
   valori ammessi. Eseguilo tre volte e confronta: il ragionamento è coerente con l'umore?
3. **L'ordine dei campi conta.** Nello stesso script metti `mood` prima di `reasoning` ed
   eseguilo più volte con frasi ambigue ("domani esame, poi festa"). *Verifica:* confronta
   quante volte il ragionamento giustifica a posteriori una decisione discutibile.
4. **Il parser su una frase tua.** In `python`:

   ```python
   from planner.agents.parser import parse_day
   from planner.config import Settings
   from planner.llm.factory import build_llm_client

   result = parse_day("domani dentista alle 15, poi se riesco palestra", build_llm_client(Settings()))
   print(result.tasks, result.warnings, sep="\n")
   ```

   *Verifica:* il dentista ha `fixed_start_min=900` (15 × 60) e `required=True`; la palestra
   non ha orari. Secondo il prompt dovrebbe avere priorità 1 ("se riesco"). Confronta con
   quello che hai ottenuto: in una prova reale il modello ha scritto questo:

   ```
   Task(id='t2', title='Palestra (facoltativa)', required=False, duration_min=60, priority=3, ...)
   ['Palestra (facoltativa): ignorato earliest_start 16:00 (non compare nella frase)']
   ```

   Il modello ha inventato un orario, e `clean_times` l'ha tolto con un avviso. Ha anche
   sbagliato la priorità, pur avendo capito che la palestra era facoltativa (lo dice il
   titolo!). Il primo errore lo ferma un controllo in Python. Il secondo no: lo può correggere
   solo l'utente nella schermata di conferma, ed è per questo che quella schermata esiste.
5. **Cambia modello.** Con `ollama pull llama3.1:8b` e `LLM_MODEL=llama3.1:8b` in `.env`,
   ripeti l'esercizio 4. *Verifica:* il programma funziona senza cambiare codice, e le
   risposte possono essere diverse. Rimetti `qwen2.5:7b` alla fine.

## Per approfondire

- Ollama: <https://ollama.com>; la pagina *Structured outputs* della documentazione
  spiega il parametro `format`.
- Libreria Python: <https://github.com/ollama/ollama-python>
- I modelli disponibili: <https://ollama.com/library>
- Prossimo capitolo: [LangGraph](03-langgraph.md), dove le chiamate all'LLM diventano nodi
  di un grafo, insieme alle pause per l'utente.
