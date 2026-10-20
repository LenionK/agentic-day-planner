# 10. FastAPI

> Versioni nel progetto: **fastapi 0.143.0**, **uvicorn 0.54.0** (il server), **httpx
> 0.28.1** (serve a `TestClient` nei test).

## Cos'è

Un'**API web** è un programma che risponde a richieste HTTP: un client manda un JSON a un
indirizzo (`POST /plans`) e riceve un JSON in risposta. Il client può essere qualunque cosa:
un'app per telefono, un altro programma, uno script, il browser.

**FastAPI** è una libreria Python per scrivere API. Scrivi una normale funzione, le dici a
quale indirizzo risponde, e FastAPI si occupa del resto:

- legge il JSON della richiesta e lo **valida con un modello Pydantic** ([capitolo
  1](01-pydantic.md)); se non è valido risponde da sola con un errore 422;
- trasforma in JSON quello che la funzione restituisce;
- genera una **pagina di documentazione interattiva** (`/docs`) da cui provare l'API.

FastAPI non apre da sola la porta di rete: lo fa **uvicorn**, il server, che riceve le
connessioni e le passa all'app.

## Perché qui

Fino alla versione 0.2 il grafo lo usava solo l'interfaccia Streamlit, nello stesso processo
Python. Con l'API qualunque programma può pianificare una giornata: è il primo passo verso
altri client (un'app, l'export del calendario `.ics`).

Il punto interessante è che **il grafo non è cambiato**. La stessa conversazione che
Streamlit gestisce con lo stato della sessione, qui diventa una sequenza di richieste HTTP
legate da un `thread_id`. È il vantaggio di aver tenuto il grafo separato dall'interfaccia.

## Concetti chiave

### Un endpoint è una funzione con un decoratore

```python
from fastapi import FastAPI

app = FastAPI(title="Agentic Day Planner")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

`@app.get("/health")` significa: "quando arriva una GET su `/health`, chiama questa
funzione". Il dizionario restituito diventa il JSON della risposta. I metodi più comuni:

- **GET** per leggere (non cambia niente sul server);
- **POST** per creare o mandare qualcosa: una pianificazione nuova, una risposta.

### Avviare il server

```
python -m uvicorn planner.api.app:app --reload
```

`planner.api.app` è il modulo (il file `src/planner/api/app.py`), `:app` è la variabile
dentro il modulo. `--reload` riavvia il server quando salvi un file: comodo durante lo
sviluppo. Il server ascolta su `http://127.0.0.1:8000`, e `Ctrl+C` lo ferma.

### `def` o `async def`?

FastAPI accetta entrambi, ma non sono equivalenti:

- una funzione `async def` gira nel ciclo principale del server: se dentro fa qualcosa di
  lento **senza** `await` (una chiamata a Ollama, una query psycopg sincrona), blocca il
  server per tutti;
- una funzione `def` normale viene eseguita in un thread a parte, e il server continua a
  rispondere agli altri.

Il grafo del progetto è tutto sincrono, quindi gli endpoint sono `def`.

### Il corpo della richiesta è un modello Pydantic

```python
class PlanRequest(BaseModel):
    text: str = Field(min_length=1)
    day_date: date


@app.post("/plans")
def start_plan(body: PlanRequest) -> PlanQuestion: ...
```

Siccome `body` è un `BaseModel`, FastAPI capisce che arriva dal corpo JSON e lo valida. Se
manca `text`, o `day_date` non è una data, **la funzione non viene neanche chiamata**: il
client riceve **422** con l'elenco degli errori, nello stesso formato di `err.errors()`.
La data arriva come testo ISO (`"2026-11-03"`) e diventa un oggetto `date`.

Il tipo di ritorno (`-> PlanQuestion`) fa tre cose: controlla quello che restituisci, lo
converte in JSON e lo descrive in `/docs`. Un endpoint che può restituire due cose diverse
lo dice con `|`: `-> PlanQuestion | PlanResult`.

### Parametri nel percorso

```python
@app.post("/plans/{thread_id}/resume")
def resume_plan(thread_id: str, body: ResumeRequest): ...
```

Le graffe indicano un pezzo variabile dell'indirizzo: con `/plans/abc/resume`, `thread_id`
vale `"abc"`. Il parametro con lo stesso nome lo riceve.

### Codici di stato e `HTTPException`

Il codice di stato dice al client com'è andata, prima ancora di leggere la risposta:

| Codice | Significato | Nel progetto |
|---|---|---|
| 200 | tutto bene | domanda successiva, piano finito, file del calendario |
| 404 | non trovato | nessuna pianificazione con quel `thread_id`, nessun piano salvato per quella data |
| 405 | metodo non permesso | l'indirizzo esiste ma con un altro metodo: una GET su `/plans`, che accetta solo POST |
| 409 | conflitto con lo stato attuale | la pianificazione è finita, non aspetta risposte |
| 422 | dati non validi | corpo sbagliato, data non valida, o risposta che il grafo rifiuta |
| 503 | servizio non disponibile | il database è spento: non ci sono piani salvati da esportare |

404 e 503 sembrano simili, ma dicono cose diverse: con 404 il database c'è e per quella data
non c'è niente; con 503 la richiesta è giusta, ma manca un servizio che serve per rispondere.

Per rispondere con un errore si **solleva** un'eccezione:

```python
raise HTTPException(status_code=404, detail="Pianificazione inesistente.")
```

FastAPI la intercetta e manda `{"detail": "Pianificazione inesistente."}` con codice 404.

### La lifespan e `app.state`: il grafo creato una volta

Il grafo (con il suo checkpointer) va creato **una volta sola**, all'avvio del server: se lo
si ricreasse a ogni richiesta, il checkpointer nuovo non conoscerebbe i grafi in pausa. La
**lifespan** è la funzione che FastAPI esegue all'avvio; il codice prima di `yield` gira
all'avvio, quello dopo alla chiusura. `app.state` è un contenitore dove metterlo:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = build_planner_graph(...)
    yield


app = FastAPI(lifespan=lifespan)
```

Ogni endpoint ritrova il grafo in `app.state.graph`. È l'equivalente di `cache_resource` in
Streamlit ([capitolo 5](05-streamlit.md)).

### La funzione che crea l'app

L'app non è creata direttamente nel modulo ma da una funzione, `create_app(graph=None)`:

- il server la chiama senza argomenti, e la lifespan costruisce il grafo vero (Ollama, e il
  database se risponde);
- i test le passano un grafo costruito su un LLM finto.

Gli endpoint e la lifespan sono definiti **dentro** `create_app`: sono funzioni annidate,
che si ricordano il `graph` ricevuto e l'`app` a cui appartengono anche dopo che
`create_app` è finita (una *closure*).

### Una conversazione fatta di più richieste

Il grafo si ferma a ogni domanda per l'utente (`interrupt`, [capitolo 3](03-langgraph.md)).
Via HTTP diventa così:

1. `POST /plans` con frase e data → il grafo parte con un `thread_id` nuovo (`uuid4`) e si
   ferma alla prima domanda; la risposta contiene il `thread_id`, lo `step` e il contenuto
   della domanda.
2. `POST /plans/{thread_id}/resume` con `{"answer": {...}}` → il grafo riprende con
   `Command(resume=answer)` e restituisce la domanda successiva, oppure `"step": "done"`
   con piano, critica ed esito del salvataggio.
3. Si ripete il punto 2 finché lo `step` non è `"done"`.

Il formato di `answer` dipende dalla domanda, ed è il grafo a validarlo:

| `step` | `answer` |
|---|---|
| `confirm_tasks`, `resolve_conflict` | `{"edits": {"t2": {"priority": 1}}}` (`{"edits": {}}` = tutto va bene) |
| `review_plan` | `{"accept": true}` |
| `suggest_activities` | `{"accepted": [0]}` |
| `confirm_preferences` | `{"keep": [0], "delete": []}` |

Prima di riprendere, l'endpoint guarda lo stato del thread con `graph.get_state(config)`:
`.values` vuoto vuol dire che il thread non esiste (404), `.next` vuoto che il grafo è
arrivato alla fine (409).

### `/docs`: la documentazione che si scrive da sola

FastAPI descrive l'API in un formato standard (*OpenAPI*, visibile su `/openapi.json`) e ne
ricava la pagina `/docs`: ogni endpoint con i suoi modelli, e il bottone "Try it out" per
mandare richieste vere dal browser. I modelli Pydantic compaiono nella sezione *Schemas*.

### Rispondere con un file: l'export `.ics`

`GET /days/2026-11-03/plan.ics` restituisce il piano salvato di quel giorno come file
**iCalendar**, il formato standard che leggono tutte le app di calendario. Il file è fatto di
blocchi `BEGIN:`/`END:`: un `VCALENDAR` che contiene un `VEVENT` per ogni task del piano, con
titolo (`SUMMARY`), inizio e fine (`DTSTART`, `DTEND`), la frase dell'utente
(`DESCRIPTION`) e un identificativo (`UID`). Lo scrive la libreria **icalendar**, che si
occupa delle regole scomode del formato: righe che finiscono con `\r\n`, righe lunghe spezzate,
virgole e punti e virgola da far precedere da `\`.

Tre scelte che vale la pena notare in
[export/ics.py](../../src/planner/export/ics.py):

- **`UID` stabile**, costruito da data e id del task (`2026-11-03-t1@agentic-day-planner`):
  è il modo standard per dire al calendario "è lo stesso evento di prima", così un file
  importato di nuovo può aggiornare gli eventi invece di duplicarli (quanto lo rispetti,
  dipende dall'app).
- **Orari con il fuso** (`DTSTART;TZID=Europe/Rome:20261103T093000`), non "fluttuanti": ogni
  app li mette all'ora giusta, anche con l'ora legale. Il fuso si sceglie con `TIMEZONE` in
  `.env`; il blocco `VTIMEZONE` che lo descrive lo genera `add_missing_timezones()`.
- **L'ora "iniettata"**: `DTSTAMP` (quando è stato creato il file) cambia a ogni esecuzione,
  quindi la funzione riceve `now` come parametro e i test le passano una data fissa.

Per l'endpoint, la novità è che la risposta non è JSON. Si restituisce direttamente un
`Response` con i bytes del file:

```python
return Response(
    content=day_to_ics(saved, app.state.timezone),
    media_type="text/calendar",
    headers={"Content-Disposition": f'attachment; filename="piano-{day_date}.ics"'},
)
```

- `media_type` è il **tipo MIME**: dice al client cosa contengono i bytes. Con
  `text/calendar` un telefono propone di aprire il file con l'app del calendario.
- `Content-Disposition: attachment` dice al browser di **scaricare** il file con quel nome,
  invece di mostrarlo come testo.
- Il parametro `day_date: date` nel percorso viene convertito e validato come un corpo JSON:
  `/days/domani/plan.ics` dà 422.

### `TestClient`: provare l'API senza server

```python
from fastapi.testclient import TestClient

with TestClient(create_app(grafo_finto)) as client:
    reply = client.post("/plans", json={"text": "studio", "day_date": "2026-11-03"})
assert reply.status_code == 200
```

`TestClient` manda le richieste direttamente all'app, senza rete. Con il `FakeClient` al
posto di Ollama i test girano in pochi secondi e danno sempre lo stesso risultato
([capitolo 9](09-test-e-valutazione.md)).

### Gli altri endpoint: storico, preferenze, errori del database

Per fare tutto quello che fa Streamlit, all'API servono anche:

| Endpoint | Cosa fa |
|---|---|
| `GET /days` | le giornate salvate, la più recente prima, ognuna con il suo piano (lo Storico) |
| `GET /preferences` | le preferenze ricordate |
| `DELETE /preferences/{id}` | dimentica una preferenza: **204** (fatto, risposta senza corpo) o 404 |

**DELETE** è il metodo HTTP per cancellare, e **204 No Content** è la risposta di chi ha fatto
quello che gli si chiedeva e non ha niente da restituire: si ottiene con
`@app.delete(..., status_code=204)` e una funzione che non restituisce niente.

Un database che si spegne **dopo** l'avvio fa sollevare a psycopg un `OperationalError` in
mezzo a una richiesta. Senza fare niente, il client riceverebbe un generico 500. Un
**gestore di eccezioni** lo trasforma una volta per tutte, per ogni endpoint:

```python
@app.exception_handler(psycopg.OperationalError)
def database_down(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Database non raggiungibile."})
```

### Una pagina web: un altro client della stessa API

Su `http://127.0.0.1:8000/` l'API serve una pagina con le stesse schermate di Streamlit. La
pagina **non ha niente di speciale**: è un client come i test, `/docs` o PowerShell, e ogni
passo è una richiesta all'API. È la prova che la separazione funziona.

È fatta di tre file in [api/static/](../../src/planner/api/static/):

- `index.html` (la struttura), servito su `/` con `FileResponse` e `include_in_schema=False`
  (la pagina non fa parte dell'API, quindi non compare in `/docs`);
- `style.css` (l'aspetto) e `app.js` (il comportamento), serviti da
  `app.mount("/static", StaticFiles(directory=STATIC))`, che rende raggiungibili tutti i
  file di una cartella.

Le idee di JavaScript che servono, confrontate con Python:

| JavaScript | Python | Cosa fa |
|---|---|---|
| `await fetch("/plans", {method: "POST", body: ...})` | `client.post("/plans", json=...)` | manda una richiesta e aspetta la risposta |
| `JSON.stringify(x)` / `await response.json()` | `json.dumps(x)` / `response.json()` | oggetto ↔ testo JSON |
| `document.querySelector("#text")` | — | trova un elemento della pagina |
| `form.addEventListener("submit", f)` | — | "quando il modulo viene inviato, chiama f" |
| `event.preventDefault()` | — | blocca il comportamento normale (il form ricaricherebbe la pagina) |

Tre scelte da notare in `app.js`:

- **`textContent`, mai `innerHTML`.** Ogni testo (la frase dell'utente, i titoli e i commenti
  dell'LLM) entra nella pagina come testo. Con `innerHTML` un titolo come
  `<img src=x onerror=...>` diventerebbe codice eseguito dal browser: è l'attacco chiamato
  *cross-site scripting* (XSS). Nella prova del libretto un titolo `Progetto <b>lungo</b>`
  compare così com'è, con i simboli visibili.
- **`<script type="module">`.** Le variabili dello script restano sue: `alert` o `screen`,
  che il browser ha già come nomi globali, non vengono toccati.
- **Stessa origine.** La pagina e l'API stanno sullo stesso indirizzo, quindi il browser
  permette le richieste senza configurare il CORS (che servirebbe se la pagina stesse altrove).

Le finestre Storico e Preferenze sono elementi `<dialog>` aperti con `showModal()`: una
finestra modale che si chiude con Esc. Il **tema scuro** cambia solo le variabili dei
colori (`--bg`, `--text`...): segue il tema del sistema (`prefers-color-scheme`), oppure la
scelta fatta col bottone 🌙/☀️, salvata nel browser con `localStorage`.

## Dove guardare nel codice

- [api/app.py](../../src/planner/api/app.py): `create_app` con lifespan ed endpoint;
  `build_planner_graph` (gli stessi ingredienti dell'interfaccia); `reply`, che trasforma il
  risultato del grafo in domanda o piano finito.
- [api/schemas.py](../../src/planner/api/schemas.py): i modelli di richieste e risposte, il
  "contratto" dell'API.
- [export/ics.py](../../src/planner/export/ics.py): la giornata salvata come file `.ics`.
- [api/static/app.js](../../src/planner/api/static/app.js): la pagina web; `api()` per le
  richieste, `render()` sceglie la schermata dallo `step`, `diffEdits()` manda solo i campi
  cambiati (come `diff_edits` di Streamlit).
- [tests/unit/test_api.py](../../tests/unit/test_api.py): i test, compreso un piano
  completo, una risposta sbagliata seguita da quella giusta, il salvataggio con un archivio
  finto e lo stesso piano scaricato come calendario.
- [tests/unit/test_ics.py](../../tests/unit/test_ics.py): il file `.ics` riletto con
  `Calendar.from_ical`, compresi l'ora legale e i caratteri da proteggere.

## Trappole incontrate

### `TestClient` senza `with`: la lifespan non parte

**Sintomo:** `AttributeError: 'State' object has no attribute 'database'`.
**Causa:** `TestClient(app).get(...)` manda la richiesta senza eseguire la lifespan, quindi
`app.state` è vuoto.
**Correzione:** sempre `with TestClient(app) as client:`.

### Una risposta vuota ripresenta quella sbagliata di prima

Sapevamo già che `Command(resume={})` non riprende il grafo: un dizionario vuoto viene letto
come "nessuna risposta per nessuna domanda". Provando l'API è emerso di peggio: se prima era
stata mandata una risposta non valida, `{}` **riapplica quella vecchia risposta**, e il
client riceve di nuovo il suo errore, che non c'entra niente con quello che ha mandato.
**Correzione:** `answer: dict = Field(min_length=1)` in `ResumeRequest`. La risposta vuota è
rifiutata con un 422 sul corpo, prima di arrivare al grafo. Un test controlla proprio che
l'errore riguardi `["body", "answer"]` e non la risposta precedente.

### Riprendere un grafo finito non dà errore

**Sintomo:** rimandando una risposta dopo la fine, il grafo restituiva di nuovo il risultato
finale, senza nessun avviso.
**Correzione:** controllare `snapshot.next` prima di riprendere, e rispondere 409.

### Un errore che non si riesce a trasformare in JSON

**Il rischio:** per gli errori dei nostri validator (un orario scritto male, `"alle tre"`),
`err.errors()` contiene nel campo `ctx` l'oggetto `ValueError` originale, che non si può
convertire in JSON. Mandato così al client, invece di un 422 chiaro si avrebbe un errore del
server: un test lo verifica, e fallisce se si toglie la correzione.
**Correzione:** `err.errors(include_url=False, include_context=False)`. Il messaggio resta
completo, perché è già nel campo `msg`.

### 405 aprendo `/plans` nel browser

**Sintomo:** aprendo `http://127.0.0.1:8000/plans` nella barra degli indirizzi si ottiene
`{"detail":"Method Not Allowed"}`, codice 405.
**Causa:** la barra degli indirizzi fa sempre una **GET**, e `/plans` accetta solo **POST**.
Non è un 404: l'indirizzo esiste, ma con un altro metodo (la risposta lo dice
nell'intestazione `Allow: POST`). In più, una POST porta un corpo JSON che la barra degli
indirizzi non sa mandare.
**Correzione:** le POST si mandano da `/docs`, da `Invoke-RestMethod -Method Post` o da un
programma. Dal browser si aprono solo le GET: `/health`, `/docs` e il download del `.ics`.

### Accenti rotti in Windows PowerShell

**Sintomo:** chiamando l'API con `Invoke-RestMethod` in Windows PowerShell 5.1, le risposte
mostrano "Ã¨" al posto di "è".
**Causa:** non è l'API. PowerShell 5.1 legge la risposta con una codifica vecchia quando non
gliela si specifica. I dati arrivano corretti in UTF-8: in `/docs`, nei test e in PowerShell 7
gli accenti si vedono bene.

### Limiti che restano (per ora)

- **Il database si controlla solo all'avvio.** Se Docker si accende dopo, serve riavviare il
  server; Streamlit invece riprova a ogni interazione. (Se invece si spegne dopo, le
  richieste ricevono un 503 chiaro.)
- **I grafi in pausa vivono in memoria** (`InMemorySaver`): se il server si riavvia, le
  pianificazioni a metà si perdono, e con più processi uvicorn ognuno avrebbe la sua memoria.
  Un checkpointer su PostgreSQL risolverebbe entrambi i problemi.

## Prova tu

1. **Il server e `/docs`.** Avvia uvicorn con Ollama acceso e apri
   `http://127.0.0.1:8000/docs`. *Verifica:* ci sono sette endpoint (`GET /health`,
   `POST /plans`, `POST /plans/{thread_id}/resume`, `GET /days`, `GET /days/{day_date}/plan.ics`,
   `GET /preferences`, `DELETE /preferences/{pref_id}`) e, sotto, i modelli `PlanRequest`,
   `PlanQuestion`, `ResumeRequest`, `PlanResult`, `SavedDayView`. La pagina `/` non c'è.
2. **La pagina web.** Apri `http://127.0.0.1:8000/` e pianifica una giornata. Poi premi
   **F12**, scheda **Rete** (*Network*), e ripeti: ogni schermata è una richiesta a `plans`
   o a `resume`, con il JSON che hai visto in `/docs`. *Verifica:* la conversazione è la
   stessa, cambia solo chi la disegna.
3. **Una pianificazione completa da `/docs`.** In `/docs`, `POST /plans` → *Try it out* con
   `{"text": "domani dentista alle 15, poi se riesco palestra", "day_date": "2026-11-03"}` →
   *Execute*. Copia il `thread_id`, poi rispondi con `POST /plans/{thread_id}/resume`
   seguendo la tabella degli `step` finché non ottieni `"done"`. *Verifica:* ogni risposta ha
   lo stesso `thread_id`; alla fine ci sono `plan` e `critique`.
4. **Correggere l'LLM via API.** Nella prova reale per questo libretto il modello ha dato
   priorità 3 alla palestra, nonostante "se riesco". Alla prima domanda rispondi con
   `{"answer": {"edits": {"t2": {"priority": 1}}}}` (controlla prima che la palestra sia
   davvero `t2`). *Verifica:* la risposta arriva con `200`, e la correzione è stata applicata.
5. **Gli errori.** Sulla stessa pianificazione prova `{"answer": {}}`, poi `"alle tre"` come
   orario, poi un `thread_id` inventato. *Verifica:* 422 sul corpo, 422 sull'orario, 404.
6. **Da PowerShell.** Con il server acceso:

   ```powershell
   $q = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/plans -ContentType "application/json" -Body '{"text": "domani dentista alle 15, poi se riesco palestra", "day_date": "2026-11-03"}'
   $q.step
   $q.question.tasks
   ```

   *Verifica:* `confirm_tasks` e la tabella dei task. È lo stesso JSON di `/docs`, letto da
   un altro client: l'API non sa chi la sta usando.
7. **Nel calendario.** Apri nel browser `http://127.0.0.1:8000/days/AAAA-MM-GG/plan.ics` con
   una data che hai salvato (la trovi nello 📅 Storico di Streamlit) e importa il file nel tuo
   calendario (in Google Calendar: *Impostazioni → Importa ed esporta*). *Verifica:* gli
   eventi sono all'ora giusta e hanno la tua frase nella descrizione. Poi importa lo stesso
   file una seconda volta e guarda come si comporta la tua app con gli `UID` già visti:
   aggiorna o duplica?
8. **I test che possono fallire.** In [app.py](../../src/planner/api/app.py) togli il
   controllo `if not snapshot.next:` (con la sua riga `raise`) ed esegui
   `python -m pytest tests/unit/test_api.py`. *Verifica:* fallisce solo
   `test_answer_after_the_end_is_a_conflict`. Rimetti il controllo.

## Per approfondire

- Documentazione ufficiale: <https://fastapi.tiangolo.com>, in particolare il *Tutorial -
  User Guide* (path parameters, request body, response model, handling errors) e la pagina
  *Lifespan Events*.
- Test: la pagina *Testing* della documentazione, per `TestClient`.
- uvicorn: <https://www.uvicorn.org>
- I codici di stato HTTP: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Status>
