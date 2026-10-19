# TODO

## Fatto
- [x] Struttura del repo, dipendenze, PostgreSQL + pgvector in Docker
- [x] Modelli dati con validazione Pydantic (`Task`, `DayConfig`, `Schedule`)
- [x] Scheduler CP-SAT: giornata, nessuna sovrapposizione, priorità
- [x] Finestre orarie (`earliest_start_min`, `deadline_min`) e orari fissi
- [x] Task impossibili esclusi senza far fallire il resto del piano
- [x] Pesi delle priorità: un task di priorità più alta batte qualunque numero di task più bassi
- [x] Task obbligatori (`required`)
- [x] Client LLM: interfaccia `LLMClient`, retry con l'errore di validazione, configurazione da `.env`, factory
- [x] Client LangChain (`ChatOllama`), equivalente a `OllamaClient` a parità di parametri
- [x] Parser: frase libera → lista di `Task`, con output strutturato, `source` per task, pulizia degli orari e avvisi
- [x] Set di valutazione del Parser (13 casi) e script `run_eval.py` (`tests/eval/RESULTS.md` non è mai stato aggiunto al repo)
- [x] Grafo LangGraph: Parser → conferma utente (`ask_approval`) → `editor` → Scheduler
- [x] Conferma dell'utente con `interrupt`: riepilogo JSON (orari "HH:MM", scartati con motivo, avvisi; senza `source`), risposta validata con `response_schema`
- [x] Editor: applica le correzioni (priorità, obbligo, durata) con validazione e avvisi; checkpoint in modalità strict nei test
- [x] Correzioni degli orari (fisso, dopo le, entro le): "HH:MM" nella risposta, l'editor converte in minuti; orario vuoto = vincolo tolto
- [x] Interfaccia Streamlit (`src/planner/ui/app.py`): tabella modificabile (checkbox, menu 1–5, durata, selettore orari), invio con Invio, "Continua senza modifiche"
- [x] Revisione del piano: secondo `interrupt` dopo lo scheduler e arco condizionale; "accetta" → fine, "modifica" → di nuovo la conferma dei task, già corretti
- [x] Gestione dei conflitti, con instradamento dopo lo scheduler: tutto inserito → fine; task esclusi → revisione; obbligatori in conflitto → `resolve_conflict` (solo i task in conflitto, risposta nel formato delle correzioni) → editor → scheduler
- [x] Critico della giornata (`agents/critic.py`): buchi liberi e fatti calcolati in Python; nodo `critic` con LLM (valutazione → vuota sì/no → proposte) e nodo `suggest_activities` con interrupt; proposte che non entrano in nessun buco scartate con avviso; nell'interfaccia piano, fatti come dati e commento come opinione

## Prossimi passi
- [ ] Database (PostgreSQL)
  - [x] schema con Alembic: `days` (una per data) e `tasks` (chiave esterna con `ON DELETE CASCADE`)
  - [x] `store.py` (salva, rilegge, sostituisce in una transazione) e test di integrazione su `planner_test`
  - [x] salvataggio nel grafo: `check_saved_day` subito dopo il parser, `save_plan` alla fine senza altre domande; archivio iniettato con un `Protocol`
  - [x] unione: se la data ha già un piano, i suoi task si uniscono ai nuovi, bloccati al loro orario (solo per il solver); il Critico valuta la giornata intera; "Sostituisci il piano salvato" nella conferma
  - [x] interfaccia: selettore della data, "Già in agenda" nella conferma, un solo bottone di conferma, esito del salvataggio
  - [x] view `day_summary` (revisione 0003): per giornata task, obbligatori, minuti e percentuale occupati; "Storico" nella barra laterale
  - [x] procedura `purge_old_days(keep_days = 14)` (revisione 0004), chiamata con `CALL` all'avvio dell'app: le giornate più vecchie di 2 settimane si cancellano, con i loro task
- [ ] Memoria delle preferenze con pgvector
  - [x] `Embedder` (Ollama, `nomic-embed-text`, prefissi document / query) e misura delle similarità (`tests/eval/run_embeddings.py`)
  - [x] estrazione delle preferenze (source → cue → text) e giudice dei duplicati, misurati su set di sviluppo e di verifica (`tests/eval/run_preferences.py`)
  - [x] tabella `preferences` (revisione 0005, un solo vettore `embedding`, nessun legame con le giornate)
  - [x] nel grafo dopo `save_plan`: estrazione → candidate (vettori + giudice) → conferma dell'utente (solo preferenze nuove) → salvataggio
  - [x] finestra "🧠 Preferenze" accanto allo Storico: elenco ed eliminazione
  - [ ] recupero: le preferenze pertinenti nel Critico e nella conferma dei task
- [ ] API FastAPI ed export `.ics`
- [ ] Eval dei modelli (Qwen2.5 7B, Phi-4 mini, Llama 3.1 8B, Aya Expanse 8B) sulla GTX 1060
- [ ] CI con GitHub Actions, AWS con LocalStack e CDK

## Estensioni
- [ ] **Funzione `frequent_tasks(n)`** nel database: task più frequenti, durata media, orario medio di inizio; da mostrare nello Storico.
- [ ] **Proposte del Critico nel piano:** le proposte accettate (`{"accepted": [...]}`) diventano `Task` con id nuovi, priorità bassa e non obbligatori, si aggiungono ai task e tornano allo scheduler; un campo nello stato fa girare il Critico una sola volta (altrimenti dopo lo scheduler si torna al Critico all'infinito). Interfaccia: una casella per proposta e "Aggiungi e ripianifica".
- [ ] **Valutazione del Critico** su giornate di prova (piene, vuote, a metà) con il giudizio atteso, anche con l'ordine dei campi invertito per misurare l'effetto del ragionamento prima della decisione.
- [ ] **Critico del parser:** controlli deterministici di ogni task rispetto al suo `source` ("13 ore" → 780 minuti, "se riesco" → priorità 1, "devo" → 5), con avvisi nella conferma; misurato con `run_eval.py` prima e dopo.
- [ ] **Agente che modifica il piano a conversazione** ("sposta la palestra alle 19", "togli la spesa", "aggiungi mezz'ora di pausa dopo pranzo"). L'LLM sceglie quale tool usare:
  - aggiungi un task
  - togli un task
  - cambia orario o priorità di un task
  - ripianifica (chiama lo scheduler)
  Da valutare come il Parser: con un 7B il tool calling è meno affidabile dell'output strutturato.
- [ ] Client LangChain generico: riceve una funzione "schema → modello chat" invece di creare sempre `ChatOllama`; la factory sceglie il provider (Ollama, Groq...). Così Groq diventa una funzione nella factory, non una classe nuova.

## Parser: miglioramenti
- [ ] Scrivere casi di valutazione **nuovi**, mai usati durante le modifiche al prompt, per misurare il risultato reale (l'8/13 attuale è probabilmente ottimista)
- [ ] L'esempio nel prompt "contagia" altri task (la spesa con "se riesco" riceve l'orario 20:00 della corsa)
- [ ] "Devo" a volte rende ancora un task obbligatorio (casi 1 e 11)
- [ ] Il `source` a volte ingloba un pezzo del task successivo (caso 7)
- [ ] Lettere di altri alfabeti nel `source` ("dентista"): normalizzare se un giorno il `source` verrà mostrato all'utente o confrontato
- [ ] Esperimento: `LLM_REPEAT_PENALTY=1.0` misurato sulla valutazione completa
- [ ] Orari a parole ("alle tre", "mezzogiorno"): la pulizia degli orari riconosce solo numeri

## Solver: miglioramenti
- [ ] `preferred_period` (mattina/pomeriggio/sera) come premio nell'obiettivo, non come vincolo
- [ ] Tempo libero (`free_time_min`): decidere tra minimo totale non pianificato o blocco unico
- [ ] Criteri secondari tra soluzioni equivalenti (giornata compatta, pause)
- [ ] Slot da 15 minuti (`slot_min`), solo se servirà più velocità

## Decisioni prese
- **Priorità:** suggerita dal Parser in base agli indizi nel testo ("devo" → 5, "se riesco" → 1, altrimenti 3); l'utente la conferma o la corregge prima di generare il piano.
- **Obbligo e priorità sono indipendenti:** "devo" alza la priorità ma non rende un task obbligatorio. Obbligatorio solo con un'espressione esplicita ("non posso saltare") o un orario di inizio preciso.
- **Obbligatorio ⇒ priorità 5:** lo impongono in Python il Parser e l'editor, non il modello. Non è un validator di `Task`: per lo scheduler obbligo e priorità restano indipendenti.
- **Conferma dell'utente:** il riepilogo non mostra il `source` (serve solo al grounding del Parser). La risposta contiene solo le differenze (`{"edits": {"t2": {"priority": 2}}}`, `{"edits": {}}` = confermo tutto), non la lista completa.
- **Editor separato da chi decide:** interfaccia e futuro agente producono lo stesso formato di correzioni; l'editor le valida e le applica. Correzione su id inesistente o che rende il task invalido: ignorata per intero, con avviso.
- **Interfaccia:** Streamlit per ora (solo Python); FastAPI quando servirà un'API vera (`.ics`, altri client). Il grafo non cambia.
- **Database, una giornata per data:** vincolo `UNIQUE (day_date)` come ultima difesa. Il controllo avviene subito dopo il parser, non alla fine: se la data esiste già, i task salvati entrano nella conferma (non modificabili, bloccati al loro orario) e l'unione è il comportamento normale; "Sostituisci il piano salvato" li scarta. Alla fine la giornata viene riscritta in una transazione (i task vecchi spariscono con `ON DELETE CASCADE`). Così il Critico valuta la giornata intera. Per non toccare il piano salvato basta non confermare: si salva solo alla fine.
- **Preferenze, vettori e giudice:** gli embedding misurano l'argomento, non la polarità ("studiare la mattina" e "la sera" hanno similarità 0.93, più di molte parafrasi): il vettore sceglie solo le candidate (la nuova come query contro le salvate come document, soglia 0.63: separa meglio di clustering/clustering, e basta una colonna anche per il recupero), un LLM giudica se sono la stessa preferenza, e le contraddizioni le risolve l'utente nella conferma, dove vede le salvate simili e può cancellarle.
- **Preferenze confermate dall'utente:** una preferenza sbagliata condizionerebbe tutte le giornate future; il modello estrae, l'utente decide. Il testo deve essere in italiano: con lingue diverse la similarità crolla e le contraddizioni non vengono mostrate.
- **Pulizia delle giornate:** si tengono solo le ultime 2 settimane (più le future), con una procedura nel database chiamata all'avvio dell'app; le preferenze, in una tabella senza legami con le giornate, restano anche quando la giornata da cui sono nate viene cancellata.
- **Si salva solo il piano:** i task rimasti fuori (accettati in revisione) non entrano nel database; il messaggio finale li elenca. Le colonne `scheduled_*` di `tasks` restano annullabili, ma dall'app arrivano sempre piene.
- **Un solo bottone di conferma:** `diff_edits` capisce da solo se la tabella è cambiata; nessun checksum (servirebbe comunque sapere *cosa* è cambiato, e sarebbe fragile con "15:30" e "15:30:00.000").
- **Migrazioni con Alembic, SQL puro:** revisioni con `op.execute`, una transazione per revisione; SQLAlchemy solo come motore di Alembic, l'app usa `psycopg` diretto. Una revisione già condivisa non si modifica: se ne scrive una nuova.
- **Checkpoint:** `LANGGRAPH_STRICT_MSGPACK=true`; LangGraph ammette da solo i tipi dichiarati in `PlannerState`.
- **Domande all'utente:** ogni riepilogo passato a `interrupt` ha un campo `step` (`confirm_tasks`, `resolve_conflict`, `review_plan`) che dice al chiamante a quale domanda risponde; ogni domanda ha il suo `response_schema`.
- **Avvisi tra un giro e l'altro:** quelli del Parser restano sempre; dell'editor si tengono solo quelli dell'ultimo giro (`edit_warnings`), quelli vecchi riguardano correzioni superate.
- **Salvataggio del piano:** sarà un nodo del grafo prima di END (piano completo o accettato), non un'azione dell'interfaccia: ogni chiamante (Streamlit, API, agente) ottiene lo stesso comportamento rispondendo "accetta".
- **Task obbligatori nello scheduler:** implementati con l'opzione ___ (A = vincolo rigido, B = peso dominante).
- **Conflitto tra obbligatori:** sceglie l'utente. Lo scheduler trova il conflitto minimo, il grafo si ferma e mostra solo quei task; la risposta è una normale correzione (togliere l'obbligo, spostare un orario, accorciare) applicata dallo stesso editor. Non si può accettare un piano impossibile.
- **Revisione solo se serve:** l'utente ha già confermato task e orari; se lo scheduler li inserisce tutti il grafo finisce senza altre domande. Si chiede solo se il piano differisce da quanto confermato (task esclusi o conflitto).
- **LLM e interrupt in nodi separati:** alla ripresa un nodo riparte dall'inizio; una chiamata all'LLM nello stesso nodo dell'interrupt verrebbe rifatta.
- **Mai `Command(resume={})`:** un dict vuoto non riprende il grafo (è letto come mappa id interrupt → risposta); ogni risposta ha almeno un campo.
- **Critico della giornata:** decide l'LLM se la giornata è troppo vuota, ma riceve i buchi liberi già calcolati in Python e le sue proposte sono controllate contro i buchi reali.
- **Gestione dei conflitti, non "Critico":** non ricontrolla sovrapposizioni e vincoli, che il solver garantisce già; è la scelta di percorso dopo lo scheduler più la domanda sul conflitto. Il nome "Critico" è riservato a un passo che valuta un risultato e propone miglioramenti.
- **L'LLM fa la parte linguistica, Python i calcoli:** orari come testo "HH:MM" convertiti in Python; pulizia degli orari deterministica.
- **Grounding:** ogni task ha un `source`, il pezzo di frase che lo riguarda, generato per primo.
- **Orari inventati:** tolti solo se non compaiono nella frase, e sempre con un avviso, mai in silenzio.
- **Fasce bloccate:** rimosse, i task con finestra coprono gli stessi casi in modo più flessibile. Da riconsiderare solo per importare un calendario esterno.
- **Terminologia:** il progetto è un *flusso agentico* (agentic workflow), non un sistema multi-agente. Diventerà anche "agente" con l'estensione che modifica il piano a conversazione.