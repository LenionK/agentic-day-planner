# Libretto delle tecnologie

Questo libretto spiega le tecnologie usate in **agentic-day-planner** a chi le vuole studiare.
Non è un manuale generico: ogni concetto è mostrato nel punto del progetto in cui serve
davvero, con i link al codice e con gli errori che sono stati commessi (e corretti) lungo
la strada.

## A chi è rivolto

A chi conosce le basi di Python e vuole capire come si costruisce un'applicazione con un
LLM locale, un flusso ad agenti, un ottimizzatore e un database.

**Prerequisiti:**

- Python di base: funzioni, classi, type hint (`def f(x: int) -> str`), liste e dizionari.
- Un po' di SQL: `SELECT`, `INSERT`, `JOIN`.
- La riga di comando: aprire un terminale, lanciare un comando, leggere un errore.

Tutto il resto (Pydantic, LangGraph, CP-SAT, Streamlit, Alembic, embedding…) lo spiega il
libretto partendo da zero.

## Percorso di lettura

1. **[Architettura](architettura.md)**: il quadro d'insieme. Cosa succede dalla frase
   scritta dall'utente fino al piano salvato, e quale tecnologia interviene in ogni passo.
2. **I capitoli**, nell'ordine in cui i dati attraversano il programma: la frase diventa
   dati validati, un LLM la interpreta, un grafo coordina i passi, un solver costruisce
   l'orario, un'interfaccia lo mostra, un database lo conserva e ricorda le preferenze.
   Il capitolo 9 spiega come si verifica che tutto funzioni; il 10 apre il programma ad
   altri client con un'API web.

Ogni capitolo si legge anche da solo, ma i rimandi presuppongono questo ordine.

## Capitoli

| # | Tecnologia | Versione | Cosa si impara |
|---|---|---|---|
| 1 | [Pydantic](libretto/01-pydantic.md) | 2.14.1 | Modelli di dati validati, errori leggibili, schemi JSON da dare a un LLM |
| 2 | [Ollama e LLM locali](libretto/02-ollama-llm.md) | libreria 0.6.3, modello `qwen2.5:7b` | Far girare un modello sul proprio PC, output strutturato, scrivere prompt |
| 3 | [LangGraph](libretto/03-langgraph.md) | 1.2.14 | Stato, nodi, archi condizionali, cicli, pause per l'utente (`interrupt`), checkpointer |
| 4 | [OR-Tools CP-SAT](libretto/04-ortools-cpsat.md) | 9.15 | Descrivere un problema di orari come vincoli e lasciare al solver la soluzione ottima |
| 5 | [Streamlit](libretto/05-streamlit.md) | 1.66.0 | Interfacce web in Python, modello di riesecuzione, stato di sessione, cache, dialog |
| 6 | [PostgreSQL e psycopg](libretto/06-postgresql-psycopg.md) | PostgreSQL 16, psycopg 3.3.6 | Chiavi esterne, vincoli, view, procedure, query parametrizzate, transazioni |
| 7 | [Alembic](libretto/07-alembic.md) | 1.20.0 | Migrazioni del database versionate, upgrade e downgrade |
| 8 | [Embedding e pgvector](libretto/08-embedding-pgvector.md) | `nomic-embed-text`, immagine `pgvector/pgvector:pg16` | Trasformare frasi in vettori, similarità coseno, ricerca nel database, i limiti dei vettori |
| 9 | [Test e valutazione](libretto/09-test-e-valutazione.md) | pytest 9.1.1 | Test unitari e di integrazione, oggetti finti, test dell'interfaccia, misurare un LLM |
| 10 | [FastAPI](libretto/10-fastapi.md) | fastapi 0.143.0, uvicorn 0.54.0 | Un'API web: endpoint, validazione delle richieste, codici di stato, una conversazione con il grafo in più richieste |

Le versioni sono quelle installate nel progetto. Contano: librerie come LangGraph e
Streamlit cambiano spesso, e un esempio scritto per un'altra versione può non funzionare.
Quando consulti la documentazione ufficiale, controlla che sia quella della versione giusta
(`python -m pip show <libreria>` mostra quella installata).

## Com'è fatto un capitolo

Tutti i capitoli seguono lo stesso schema:

1. **Cos'è**: la tecnologia spiegata a chi non l'ha mai vista.
2. **Perché qui**: quale problema del progetto risolve, e perché non un'alternativa.
3. **Concetti chiave**: le idee che servono, ciascuna con un esempio minimo.
4. **Dove guardare nel codice**: i file e le righe in cui il concetto è usato davvero.
5. **Trappole incontrate**: errori veri fatti durante lo sviluppo, con il sintomo, la causa
   e la correzione. Spesso sono la parte più istruttiva.
6. **Prova tu**: piccoli esercizi da fare sul progetto, con il modo per verificare di averli
   fatti bene.
7. **Per approfondire**: la documentazione ufficiale e cosa leggere dopo.

## Prima di iniziare

Per eseguire gli esempi serve il progetto installato e funzionante: segui la sezione di
installazione del [README principale](../README.md#installation). Gli esercizi che toccano il database
richiedono Docker acceso; quelli sugli LLM richiedono Ollama acceso con i modelli scaricati.
