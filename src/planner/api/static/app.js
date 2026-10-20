// La pagina web del planner: un client dell'API, come lo sono i test e /docs.
// Mostra le stesse schermate dell'interfaccia Streamlit, ma ogni passo è una richiesta HTTP.

// ---------------------------------------------------------------- stato della pagina

const state = {
  threadId: null, // la pianificazione in corso: lo rimandiamo a ogni risposta
  dayDate: null, // il giorno pianificato, per il link al calendario
  database: false, // se l'API ha il database (piani salvati, storico, preferenze)
};

const screenBox = document.querySelector("#screen");
const errorBox = document.querySelector("#error"); // gli errori del modulo, sotto il modulo

// ---------------------------------------------------------------- costruire la pagina

// Crea un elemento HTML. I testi passano sempre da textContent, mai da innerHTML:
// una frase dell'utente o una risposta dell'LLM con "<script>" resta testo, non codice.
function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") node.textContent = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (value === true) node.setAttribute(name, "");
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

const notice = (kind, text) => el("div", { class: `alert ${kind}`, text });
const caption = (text) => el("p", { class: "caption", text });
const heading = (text) => el("h2", { text });

function table(headers, rows) {
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      {},
      el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", { text: h })))),
      el(
        "tbody",
        {},
        ...rows.map((row) =>
          el("tr", {}, ...row.map((cell) => el("td", {}, cell instanceof Node ? cell : String(cell)))),
        ),
      ),
    ),
  );
}

function buttons(...items) {
  return el("div", { class: "buttons" }, ...items);
}

// onclick riceve il bottone premuto: serve a mostrare l'attesa e gli errori proprio lì,
// dove l'utente sta guardando
function button(text, onclick, primary = false) {
  return el("button", {
    type: "button",
    class: primary ? "primary" : null,
    text,
    onclick: (event) => onclick(event.currentTarget),
  });
}

// ---------------------------------------------------------------- date e durate

// "AAAA-MM-GG" della data locale: toISOString() userebbe UTC, e vicino a mezzanotte
// darebbe il giorno sbagliato
function isoDate(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function italianDate(iso) {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
}

// scritti a mano come in planner/dates.py: non dipendono dalla lingua del browser
const WEEKDAYS = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
  "agosto", "settembre", "ottobre", "novembre", "dicembre"];

function longItalianDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return `${WEEKDAYS[date.getDay()]} ${day} ${MONTHS[month - 1]} ${year}`;
}

function durationText(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  const parts = hours ? [`${hours} h`] : [];
  if (mins || !hours) parts.push(`${mins} min`);
  return parts.join(" ");
}

// ---------------------------------------------------------------- parlare con l'API

// Una richiesta all'API: restituisce { ok, status, data }. Un errore di rete (server
// spento) diventa status 0, così chi chiama gestisce tutto nello stesso modo.
async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  try {
    const response = await fetch(url, options);
    const data = response.status === 204 ? null : await response.json();
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: "API non raggiungibile: il server è acceso?" } };
  }
}

// Il "detail" di un errore: un testo, oppure (422) la lista degli errori di validazione.
function errorText(detail) {
  if (!Array.isArray(detail)) return String(detail);
  return detail
    .map((e) => `${e.loc.filter((part) => part !== "body").join(".")}: ${e.msg}`)
    .join("; ");
}

function clearErrors() {
  errorBox.replaceChildren();
  screenBox.querySelectorAll(".alert[role='alert']").forEach((message) => message.remove());
}

// L'errore compare vicino al bottone che l'ha causato: sopra la barra dei bottoni della
// schermata, oppure sotto il modulo. In alto nella pagina, dopo un clic in fondo a una
// schermata lunga, non lo vedrebbe nessuno.
function showError(text, origin = null) {
  clearErrors();
  const message = el("div", { class: "alert error", role: "alert", text });
  const bar = origin?.closest("#screen .buttons");
  if (bar) bar.before(message);
  else errorBox.append(message);
  message.scrollIntoView({ behavior: "smooth", block: "center" });
}

// Mentre l'API lavora, il bottone premuto dice cosa sta succedendo; tutti i bottoni sono
// disattivati, per non mandare due volte la stessa risposta.
async function working(message, task, origin) {
  const label = origin.textContent;
  origin.style.minWidth = `${origin.offsetWidth}px`; // il bottone non cambia larghezza
  origin.textContent = `⏳ ${message}`;
  origin.setAttribute("aria-busy", "true");
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    return await task();
  } finally {
    origin.textContent = label;
    origin.removeAttribute("aria-busy");
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

// ---------------------------------------------------------------- la conversazione

async function startPlanning(text, dayDate, origin) {
  const result = await working("Sto leggendo la frase...", () =>
    api("POST", "/plans", { text, day_date: dayDate }), origin);
  if (!result.ok) {
    showError(`Errore ${result.status}: ${errorText(result.data.detail)}`);
    return;
  }
  state.threadId = result.data.thread_id;
  state.dayDate = dayDate;
  render(result.data);
}

// Risponde alla domanda in corso. Se la risposta non è valida (422) il grafo resta in pausa:
// l'errore si mostra sopra i bottoni della stessa schermata, e si può correggere e riprovare.
async function answer(response, errorPrefix, origin) {
  const result = await working("Sto pianificando...", () =>
    api("POST", `/plans/${state.threadId}/resume`, { answer: response }), origin);
  if (result.status === 422) {
    showError(`${errorPrefix}: ${errorText(result.data.detail)}`, origin);
    return;
  }
  if (result.status === 404) {
    showError("Questa pianificazione non c'è più (il server è stato riavviato?). Riscrivi la frase.",
      origin);
    return;
  }
  if (!result.ok) {
    showError(`Errore ${result.status}: ${errorText(result.data.detail)}`, origin);
    return;
  }
  render(result.data);
}

// Le fasi della pianificazione, e in quale fase cade ogni domanda del grafo ("step").
// Una fase senza domande (tutti i task entrano: niente revisione) risulta comunque superata.
const PHASES = ["Task", "Piano", "Critico", "Preferenze", "Fine"];
const PHASE_OF_STEP = {
  confirm_tasks: 0,
  resolve_conflict: 0,
  review_plan: 1,
  suggest_activities: 2,
  confirm_preferences: 3,
  done: 4,
};

// In cima a ogni schermata: quale giorno si sta pianificando e a che punto si è.
function progress(step) {
  const current = PHASE_OF_STEP[step];
  return el("div", { class: "progress" },
    el("p", { class: "progress-day" },
      "Pianificazione di ", el("strong", { text: longItalianDate(state.dayDate) })),
    el("ol", { class: "steps", "aria-label": "Passi della pianificazione" },
      ...PHASES.map((name, i) => el("li", {
        class: i < current ? "done" : i === current ? "current" : null,
        "aria-current": i === current ? "step" : null,
      }, el("span", { class: "dot", text: i < current ? "✓" : String(i + 1) }), name))));
}

// La schermata dipende dalla domanda a cui il grafo aspetta risposta ("step").
function render(data) {
  clearErrors();
  const draw = {
    confirm_tasks: showConfirmation,
    resolve_conflict: showConflict,
    review_plan: showReview,
    suggest_activities: showSuggestions,
    confirm_preferences: showPreferencesConfirmation,
  }[data.step];
  const content = data.step === "done" ? showFinal(data) : draw(data.question);
  screenBox.replaceChildren(progress(data.step), ...content);
  screenBox.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- pezzi comuni

const TIME_FIELDS = ["fixed_start", "earliest_start", "deadline"];

function showSchedule(plan) {
  const parts = [];
  if (plan.scheduled.length) {
    parts.push(table(["Dalle", "Alle", "Task"], plan.scheduled.map((s) => [s.start, s.end, s.title])));
  } else {
    parts.push(notice("info", "Nessun task nel piano."));
  }
  if (plan.unscheduled.length) {
    parts.push(notice("warning", `Non inseriti: ${plan.unscheduled.join(", ")}`));
  }
  return parts;
}

function showWarnings(summary) {
  return summary.warnings.map((w) => notice("warning", w));
}

function showRejected(summary) {
  return summary.rejected.map((r) => notice("error", `Scartato: ${r.title} (${r.reason})`));
}

function showPlan(plan) {
  return [heading("Piano della giornata"), ...showSchedule(plan), ...showWarnings(plan)];
}

// La tabella modificabile dei task. Restituisce la tabella e una funzione che legge,
// riga per riga, i valori che l'utente ha lasciato o cambiato.
function editTable(tasks) {
  const inputs = {};
  const rows = tasks.map((task) => {
    const fields = {
      duration_min: el("input", { type: "number", min: 1, max: 720, step: 1, value: task.duration_min }),
      priority: el("select", {}, ...[1, 2, 3, 4, 5].map((p) =>
        el("option", { value: p, selected: p === task.priority, text: String(p) }))),
      required: el("input", { type: "checkbox", checked: task.required }),
      // selettore d'orario: "HH:MM" o vuoto; vuoto = vincolo tolto
      ...Object.fromEntries(TIME_FIELDS.map((f) =>
        [f, el("input", { type: "time", step: 60, value: task[f] ?? "" })])),
    };
    inputs[task.id] = fields;
    return [task.title, fields.duration_min, fields.priority, fields.required,
      fields.fixed_start, fields.earliest_start, fields.deadline];
  });
  const view = table(
    ["Titolo", "Durata (min)", "Priorità", "Obbligatorio", "Inizio", "Dopo le", "Entro le"],
    rows,
  );
  const read = () => Object.fromEntries(Object.entries(inputs).map(([id, f]) => [id, {
    duration_min: f.duration_min.value === "" ? null : Number(f.duration_min.value),
    priority: Number(f.priority.value),
    required: f.required.checked,
    ...Object.fromEntries(TIME_FIELDS.map((t) => [t, f[t].value === "" ? null : f[t].value])),
  }]));
  return { view, read };
}

// Come diff_edits in ui/edits.py: solo i campi cambiati; {"edits": {}} se niente è cambiato.
function diffEdits(tasks, edited) {
  const edits = {};
  for (const task of tasks) {
    const row = edited[task.id];
    const changes = {};
    for (const [field, value] of Object.entries(row)) {
      if (value !== task[field]) changes[field] = value;
    }
    if (Object.keys(changes).length) edits[task.id] = changes;
  }
  return { edits };
}

// ---------------------------------------------------------------- le schermate

function showSavedDay(saved) {
  const day = italianDate(saved.day_date);
  if (saved.replaced) {
    return [notice("warning", `Il piano già salvato per il ${day} verrà sostituito da questo.`)];
  }
  return [
    notice("info", `Hai già un piano per il ${day}: i nuovi task verranno aggiunti negli spazi ` +
      "liberi, quelli già in agenda restano dove sono."),
    el("h3", { text: "Già in agenda" }),
    caption(`«${saved.user_input}»`),
    ...showSchedule(saved),
  ];
}

function showConfirmation(question) {
  const parts = [heading("Controlla i task")];
  const saved = question.saved_day;
  if (saved) parts.push(...showSavedDay(saved), el("h3", { text: "Nuovi task" }));
  let read = () => ({});
  if (question.tasks.length) {
    parts.push(caption("Puoi cambiare durata, priorità, obbligo e orari prima di pianificare. " +
      "Svuota un orario per togliere il vincolo."));
    const editor = editTable(question.tasks);
    parts.push(editor.view);
    read = editor.read;
  } else {
    parts.push(notice("info", "Nessun task riconosciuto nella frase."));
  }
  parts.push(...showRejected(question), ...showWarnings(question));

  // un solo bottone di conferma: diffEdits capisce da solo se qualcosa è cambiato
  const confirm = button("Conferma e pianifica", (origin) =>
    answer(diffEdits(question.tasks, read()), "Correzioni non valide", origin), true);
  const replace = saved && !saved.replaced
    ? button("Sostituisci il piano salvato", (origin) =>
      answer({ ...diffEdits(question.tasks, read()), replace_saved: true }, "Correzioni non valide",
        origin))
    : null;
  parts.push(buttons(confirm, replace));
  return parts;
}

function showConflict(question) {
  const editor = editTable(question.tasks);
  return [
    heading("Giornata impossibile"),
    notice("error", "Questi task obbligatori non possono stare tutti nella giornata. " +
      "Togli l'obbligo a uno di loro, oppure cambia un orario o una durata."),
    editor.view,
    ...showWarnings(question),
    // niente "continua senza modifiche": un piano impossibile non si può accettare
    buttons(button("Riprova a pianificare", (origin) =>
      answer(diffEdits(question.tasks, editor.read()), "Correzioni non valide", origin), true)),
  ];
}

function showReview(plan) {
  // si arriva qui solo se qualche task non entra: è il motivo della domanda
  const missing = plan.unscheduled;
  const verb = missing.length === 1 ? "non entra" : "non entrano";
  return [
    ...showPlan(plan),
    el("p", {}, el("strong", { text: missing.join(", ") }), ` ${verb} nella giornata. Ti va bene così?`),
    buttons(
      button("Continua senza modifiche", (origin) =>
        answer({ accept: true }, "Risposta non valida", origin), true),
      button("Modifica i task", (origin) =>
        answer({ accept: false }, "Risposta non valida", origin)),
    ),
  ];
}

// Prima i fatti, calcolati in Python; poi il commento del Critico, come opinione.
function showCritique(critique) {
  const longest = critique.longest_slot;
  const parts = [
    el("div", { class: "metrics" },
      el("div", { class: "metric", title: `${critique.busy_percent}% della giornata` },
        el("div", { class: "label", text: "Tempo occupato" }),
        el("div", { class: "value",
          text: `${durationText(critique.busy_minutes)} su ${durationText(critique.total_minutes)}` })),
      el("div", { class: "metric" },
        el("div", { class: "label", text: "Libero più lungo" }),
        el("div", { class: "value", text: longest ? `${longest.start}–${longest.end}` : "nessuno" }))),
    caption("Commento del Critico"),
    notice("info", critique.assessment),
  ];
  const considered = critique.recalled_preferences ?? [];
  if (considered.length) {
    parts.push(caption(`🧠 Preferenze considerate: ${considered.join("; ")}`));
  } else if (state.database) {
    parts.push(caption("🧠 Nessuna preferenza ricordata finora da considerare."));
  }
  return parts;
}

function showSuggestions(question) {
  return [
    ...showPlan(question.plan), // il piano su cui il Critico si esprime
    heading("Il Critico"),
    ...showCritique(question),
    el("p", { text: "Attività che potresti aggiungere:" }),
    table(["Attività", "Categoria", "Durata (min)", "Perché"],
      question.suggestions.map((s) => [s.title, s.category, s.duration_min, s.reason])),
    ...showWarnings(question),
    buttons(button("Va bene così", (origin) =>
      answer({ accepted: [] }, "Risposta non valida", origin), true)),
  ];
}

// Le preferenze trovate nella frase: l'utente sceglie quali ricordare. Accanto a una
// preferenza simile a una già salvata, quella salvata si può cancellare (una contraddizione).
function showPreferencesConfirmation(question) {
  const keep = [];
  const remove = [];
  const cards = question.preferences.map((pref) => {
    const keepBox = el("input", { type: "checkbox", checked: true });
    keep.push([pref.index, keepBox]);
    const similar = pref.similar.map((saved) => {
      const box = el("input", { type: "checkbox" });
      remove.push([saved.id, box]);
      return el("label", { class: "check" }, box, `Cancella quella già salvata: ${saved.text}`);
    });
    return el("div", { class: "card" },
      el("label", { class: "check" }, keepBox, el("strong", { text: pref.text })),
      caption(`«${pref.source}»`),
      ...similar);
  });
  const chosen = (pairs) => pairs.filter(([, box]) => box.checked).map(([id]) => id);
  return [
    heading("Ho capito queste preferenze"),
    caption("Spunta quelle da ricordare: le userò per le prossime giornate."),
    ...cards,
    buttons(button("Conferma", (origin) =>
      answer({ keep: chosen(keep), delete: chosen(remove) }, "Risposta non valida", origin), true)),
  ];
}

function showSaveResult(saved) {
  if (saved === null) return [notice("success", "✅ Piano confermato.")]; // senza database
  if (!saved.saved) return [notice("warning", `⚠️ ${saved.message}`)]; // non salvato: va notato
  return [
    notice("success", `✅ ${saved.message}`),
    el("p", {}, el("a", { href: `/days/${state.dayDate}/plan.ics`, text: "📥 Scarica nel calendario (.ics)" })),
  ];
}

function showFinal(result) {
  const yes = (value) => (value ? "✓" : "");
  const parts = [
    ...showPlan(result.plan),
    heading("Il Critico"),
    ...showCritique(result.critique),
    heading("Task confermati"),
    // confermati non vuol dire inseriti: la prima colonna dice dove è finito ognuno
    table(
      ["Nel piano", "Titolo", "Durata (min)", "Priorità", "Obbligatorio", "Inizio", "Dopo le", "Entro le"],
      result.tasks.map((t) => [t.slot ?? "non inserito", t.title, t.duration_min, t.priority,
        yes(t.required), t.fixed_start ?? "", t.earliest_start ?? "", t.deadline ?? ""]),
    ),
    ...showRejected(result),
    el("hr"),
    ...showSaveResult(result.save_result),
  ];
  // il passaggio delle preferenze si vede sempre, anche quando non c'era niente da chiedere
  if (result.preference_candidates !== null) {
    const message = result.preference_result?.message;
    if (message) parts.push(notice("info", `🧠 ${message}`));
    else if (result.preference_candidates === 0) {
      parts.push(caption("🧠 Nessuna preferenza da ricordare in questa frase."));
    } else parts.push(caption("🧠 Nessuna preferenza ricordata."));
  }
  return parts;
}

// ---------------------------------------------------------------- le finestre

function openDialog(id, fill) {
  const dialog = document.querySelector(id);
  const body = dialog.querySelector(".dialog-body");
  body.replaceChildren(caption("Carico..."));
  dialog.showModal(); // finestra modale: Esc la chiude
  fill(body);
}

async function fillHistory(body) {
  const result = await api("GET", "/days");
  if (!result.ok) {
    body.replaceChildren(notice("error", errorText(result.data.detail)));
    return;
  }
  if (!result.data.length) {
    body.replaceChildren(notice("info", "Nessuna giornata salvata."));
    return;
  }
  body.replaceChildren(...result.data.flatMap((day) => [
    el("p", {},
      el("strong", { text: longItalianDate(day.day_date) }),
      ` · tempo libero ${durationText(day.free_minutes)} · `,
      el("a", { href: `/days/${day.day_date}/plan.ics`, text: "📥 .ics" })),
    caption(`«${day.user_input}»`),
    day.scheduled.length
      ? table(["Dalle", "Alle", "Task"], day.scheduled.map((s) => [s.start, s.end, s.title]))
      : notice("info", "Nessun task nel piano."),
  ]));
}

async function fillPreferences(body) {
  const result = await api("GET", "/preferences");
  if (!result.ok) {
    body.replaceChildren(notice("error", errorText(result.data.detail)));
    return;
  }
  if (!result.data.length) {
    body.replaceChildren(notice("info", "Nessuna preferenza ricordata: nascono dalle frasi delle giornate salvate."));
    return;
  }
  const remove = async (id) => {
    const deleted = await api("DELETE", `/preferences/${id}`);
    if (!deleted.ok) body.prepend(notice("error", errorText(deleted.data.detail)));
    else fillPreferences(body); // l'elenco ridisegnato è già senza la preferenza cancellata
  };
  body.replaceChildren(
    caption("Le userò per le prossime giornate. Elimina quelle che non valgono più."),
    ...result.data.map((pref) => {
      const times = pref.times_seen === 1 ? "1 volta" : `${pref.times_seen} volte`;
      return el("div", { class: "card row" },
        el("div", {},
          el("strong", { text: pref.text }),
          caption(`Vista ${times} · ultima il ${italianDate(pref.last_seen)} · «${pref.source}»`)),
        button("Elimina", () => remove(pref.id)));
    }),
  );
}

function showToast(text) {
  const toast = document.querySelector("#toast");
  toast.textContent = text;
  toast.hidden = false;
  setTimeout(() => (toast.hidden = true), 5000); // scompare da solo, come st.toast
}

// ---------------------------------------------------------------- tema chiaro / scuro

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

// Il tema in uso: quello scelto col bottone, altrimenti quello del sistema.
function currentTheme() {
  return document.documentElement.dataset.theme ?? (darkQuery.matches ? "dark" : "light");
}

// Il bottone mostra il tema in cui si passa: 🌙 se ora è chiaro, ☀️ se ora è scuro.
function updateThemeButton() {
  const dark = currentTheme() === "dark";
  const toggle = document.querySelector("#theme");
  toggle.textContent = dark ? "☀️" : "🌙";
  toggle.title = dark ? "Tema chiaro" : "Tema scuro";
  toggle.setAttribute("aria-label", toggle.title);
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  // localStorage: la scelta resta per le prossime aperture, solo in questo browser.
  // Può non esserci (finestra anonima, dati bloccati): allora vale solo fino alla chiusura
  try {
    localStorage.setItem("theme", next);
  } catch {
    // nessun problema: il tema è già applicato
  }
  updateThemeButton();
}

// ---------------------------------------------------------------- avvio

async function start() {
  updateThemeButton();
  document.querySelector("#theme").addEventListener("click", toggleTheme);
  // se il tema del sistema cambia mentre la pagina è aperta, il bottone si aggiorna
  darkQuery.addEventListener("change", updateThemeButton);

  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  document.querySelector("#day").value = isoDate(tomorrow);

  document.querySelector("#new-plan").addEventListener("submit", (event) => {
    event.preventDefault(); // niente ricarica: la richiesta la fa fetch, in JSON
    const text = document.querySelector("#text").value.trim();
    if (!text) {
      showError("Scrivi cosa devi fare.");
      return;
    }
    // event.submitter: il bottone che ha inviato il modulo (anche con Invio nel campo)
    const origin = event.submitter ?? document.querySelector("#new-plan button[type=submit]");
    startPlanning(text, document.querySelector("#day").value, origin);
  });
  document.querySelector("#open-history").addEventListener("click", () =>
    openDialog("#history-dialog", fillHistory));
  document.querySelector("#open-preferences").addEventListener("click", () =>
    openDialog("#preferences-dialog", fillPreferences));
  document.querySelectorAll("dialog .close").forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()));

  const health = await api("GET", "/health");
  state.database = health.ok && health.data.database;
  if (!health.ok) {
    showError(errorText(health.data.detail));
  } else if (!state.database) {
    document.querySelector("#banner").replaceChildren(
      notice("warning", "Database non raggiungibile: i piani non verranno salvati. Avvia Docker e riavvia l'API."));
  } else {
    document.querySelector("#actions").hidden = false; // senza database i bottoni non ci sono
    if (health.data.purged) {
      const days = health.data.purged === 1 ? "1 giornata" : `${health.data.purged} giornate`;
      showToast(`🧹 Cancellate ${days} più vecchie di 2 settimane.`);
    }
  }
}

start();
