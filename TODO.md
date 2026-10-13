# TODO

## Fatto
- [x] Struttura del repo, dipendenze, PostgreSQL + pgvector in Docker
- [x] Modelli dati con validazione Pydantic (`Task`, `DayConfig`, `Schedule`)
- [x] Scheduler CP-SAT: giornata, nessuna sovrapposizione, priorità
- [x] Finestre orarie (`earliest_start_min`, `deadline_min`) e orari fissi
- [x] Task impossibili esclusi senza far fallire il resto del piano
- [x] Pesi delle priorità: un task di priorità più alta batte qualunque numero di task più bassi
- [x] Task obbligatori (`required`)

## Prossimi passi
- [ ] Client LLM (Ollama, con interfaccia per cambiare provider)
- [ ] Parser: frase libera → lista di `Task`, con output strutturato e retry
- [ ] Database: tabelle, view e stored procedure
- [ ] Memoria con pgvector (preferenze e giornate passate)
- [ ] Critico e grafo LangGraph
- [ ] API FastAPI ed export `.ics`
- [ ] Eval dei modelli (Qwen2.5 7B, Phi-4 mini, Llama 3.1 8B, Aya Expanse 8B)
- [ ] CI con GitHub Actions, AWS con LocalStack e CDK

## Solver: miglioramenti
- [ ] `preferred_period` (mattina/pomeriggio/sera) come premio nell'obiettivo, non come vincolo
- [ ] Criteri secondari tra soluzioni equivalenti (giornata compatta, pause)
- [ ] Slot da 15 minuti (`slot_min`), solo se servirà più velocità

## Decisioni prese
- **Priorità:** la assegna l'utente. Il Parser mette il default 3 e cambia solo con indizi espliciti nel testo.
- **Task obbligatori:** implementati con l'opzione ___ (A = vincolo rigido, B = peso dominante).
- **Conflitto tra obbligatori:** sceglie l'utente. Il Critico rileva il conflitto e il grafo si ferma per chiedere (interrupt di LangGraph).
- **Fasce bloccate:** rimosse, i task con finestra coprono gli stessi casi in modo più flessibile. Da riconsiderare solo per importare un calendario esterno.
- **Priorità suggerita dal Parser:** il modello propone una priorità in base agli indizi nel testo, l'utente la conferma o la corregge prima di generare il piano.