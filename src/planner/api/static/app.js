// La pagina web del planner: un client dell'API, come lo sono i test e /docs.
// Ogni schermata è una domanda del grafo, e ogni risposta una richiesta HTTP.

import { LANGUAGES, STRINGS } from "./i18n.js";

// ---------------------------------------------------------------- stato della pagina

const state = {
  threadId: null, // la pianificazione in corso: lo rimandiamo a ogni risposta
  dayDate: null, // il giorno pianificato, per il link al calendario
  text: null, // la frase della pianificazione in corso
  done: false, // il grafo è arrivato alla fine: ricominciare non perde niente
  database: false, // se l'API ha il database (piani salvati, storico, preferenze)
  language: savedLanguage(), // la lingua della pagina e dei messaggi chiesti all'API
  last: null, // l'ultima risposta dell'API: cambiando lingua, la schermata si ridisegna
  bannerKey: null, // l'avviso in cima (senza database), da ritradurre cambiando lingua
  health: null, // l'ultimo /health: Ollama e i modelli, finché non sono pronti
};

const form = document.querySelector("#new-plan");
const summaryBox = document.querySelector("#summary"); // il modulo chiuso in una riga
const screenBox = document.querySelector("#screen");
const errorBox = document.querySelector("#error"); // gli errori del modulo, sotto il modulo

// ---------------------------------------------------------------- lingua

// La lingua scelta l'ultima volta; la prima volta, l'inglese.
function savedLanguage() {
  try {
    const saved = localStorage.getItem("language");
    if (saved in LANGUAGES) return saved;
  } catch {
    // dati del browser bloccati: si usa il default
  }
  return "en";
}

// Il testo `key` nella lingua della pagina, con i {segnaposti} riempiti da `values`.
function t(key, values = {}) {
  const text = STRINGS[state.language][key] ?? STRINGS.en[key];
  if (typeof text !== "string") return text; // liste e tabelle (giorni, mesi, categorie)
  return text.replace(/\{(\w+)\}/g, (_, name) => String(values[name]));
}

// I testi scritti nell'HTML: ogni elemento dice con data-i18n quale testo gli spetta,
// con data-i18n-placeholder e data-i18n-label quale segnaposto o etichetta accessibile.
function translateStatic() {
  document.documentElement.lang = state.language;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
    node.hidden = node.textContent === ""; // un testo vuoto in una lingua: niente riga vuota
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nLabel));
  });
  markChoices();
}

// Nei gruppi di scelta (lingua, tema) aria-pressed dice quale è scelta: lo stile la evidenzia
// e un lettore di schermo la annuncia come "premuto".
function markChoices() {
  document.querySelectorAll("#language button").forEach((choice) => {
    choice.setAttribute("aria-pressed", String(choice.dataset.language === state.language));
  });
  document.querySelectorAll("#theme button").forEach((choice) => {
    choice.setAttribute("aria-pressed", String(choice.dataset.themeChoice === themeChoice()));
  });
}

// Cambiare lingua ridisegna tutto quello che si vede. I messaggi già scritti dall'API per la
// pianificazione in corso restano nella lingua in cui è cominciata.
function setLanguage(language) {
  state.language = language;
  try {
    localStorage.setItem("language", language);
  } catch {
    // nessun problema: la lingua vale fino alla chiusura
  }
  translateStatic();
  if (state.bannerKey) showBanner(state.bannerKey);
  showModels();
  if (state.threadId) collapseForm();
  if (state.last) render(state.last, { scroll: false });
  document.querySelectorAll("dialog[open]").forEach((dialog) => refill(dialog));
}

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
// dove l'utente sta guardando. kind: true o "primary" per l'azione principale della
// schermata (una sola), "danger" per un'azione che cancella qualcosa.
function button(text, onclick, kind = null) {
  return el("button", {
    type: "button",
    class: kind === true ? "primary" : kind,
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

function dateParts(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  const weekday = new Date(year, month - 1, day).getDay();
  return {
    weekday: t("weekdays")[weekday],
    day,
    month: t("months")[month - 1],
    month2: String(month).padStart(2, "0"),
    year,
  };
}

const longDate = (iso) => t("long_date", dateParts(iso)); // "Tuesday 3 November 2026"
const shortDate = (iso) => t("short_date", dateParts(iso)); // "3 November 2026", "03/11/2026"

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
// Accept-Language chiede all'API i messaggi nella lingua della pagina.
async function api(method, url, body) {
  const options = { method, headers: { "Accept-Language": state.language } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  try {
    const response = await fetch(url, options);
    const data = response.status === 204 ? null : await response.json();
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: t("api_down") } };
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
  const result = await working(t("reading"), () =>
    api("POST", "/plans", { text, day_date: dayDate }), origin);
  if (!result.ok) {
    showError(t("error_status", { status: result.status, detail: errorText(result.data.detail) }));
    return;
  }
  state.threadId = result.data.thread_id;
  state.dayDate = dayDate;
  state.text = text;
  state.done = false;
  collapseForm();
  render(result.data);
}

// Durante una pianificazione il modulo si chiude in una riga: resta chiaro che cosa si sta
// pianificando, e ricominciare diventa una scelta esplicita, non un invio fatto per sbaglio.
function collapseForm() {
  form.hidden = true;
  const actions = el("div", { class: "buttons summary-actions" },
    button(t("new_plan"), () => askRestart(actions)));
  summaryBox.replaceChildren(
    el("div", {},
      el("strong", { text: longDate(state.dayDate) }),
      caption(`«${state.text}»`)),
    actions);
  summaryBox.hidden = false;
}

// A piano finito si ricomincia subito; a metà, il piano in corso andrebbe perso: prima si
// chiede, lì accanto al bottone.
function askRestart(actions) {
  if (state.done) {
    restart();
    return;
  }
  actions.replaceChildren(
    el("span", { class: "caption", text: t("plan_lost") }),
    button(t("cancel"), collapseForm),
    button(t("restart"), restart, "danger"));
}

// Torna al modulo, con la frase di prima già scritta: spesso si vuole solo correggerla.
function restart() {
  state.threadId = null;
  state.done = false;
  state.last = null;
  clearErrors();
  screenBox.replaceChildren();
  summaryBox.hidden = true;
  form.hidden = false;
  const input = document.querySelector("#text");
  input.value = state.text ?? "";
  input.focus();
  input.select();
}

// Risponde alla domanda in corso. Se la risposta non è valida (422) il grafo resta in pausa:
// l'errore si mostra sopra i bottoni della stessa schermata, e si può correggere e riprovare.
async function answer(response, errorKey, origin) {
  const result = await working(t("planning"), () =>
    api("POST", `/plans/${state.threadId}/resume`, { answer: response }), origin);
  if (result.status === 422) {
    showError(`${t(errorKey)}: ${errorText(result.data.detail)}`, origin);
    return;
  }
  if (result.status === 404) {
    showError(t("plan_gone"), origin);
    return;
  }
  if (!result.ok) {
    showError(t("error_status", { status: result.status, detail: errorText(result.data.detail) }),
      origin);
    return;
  }
  render(result.data);
}

// Le fasi della pianificazione, e in quale fase cade ogni domanda del grafo ("step").
// Una fase senza domande (tutti i task entrano: niente revisione) risulta comunque superata.
const PHASES = ["phase_tasks", "phase_plan", "phase_critic", "phase_preferences", "phase_end"];
const PHASE_OF_STEP = {
  confirm_tasks: 0,
  resolve_conflict: 0,
  review_plan: 1,
  suggest_activities: 2,
  confirm_preferences: 3,
  done: 4,
};

// In cima a ogni schermata: a che punto si è (il giorno è già nella riga del modulo chiuso).
function progress(step) {
  const current = PHASE_OF_STEP[step];
  return el("div", { class: "progress" },
    el("ol", { class: "steps", "aria-label": t("steps") },
      ...PHASES.map((key, i) => el("li", {
        class: i < current ? "done" : i === current ? "current" : null,
        "aria-current": i === current ? "step" : null,
      }, el("span", { class: "dot", text: i < current ? "✓" : String(i + 1) }), t(key)))));
}

// La schermata dipende dalla domanda a cui il grafo aspetta risposta ("step").
function render(data, { scroll = true } = {}) {
  clearErrors();
  state.last = data;
  state.done = data.step === "done";
  const draw = {
    confirm_tasks: showConfirmation,
    resolve_conflict: showConflict,
    review_plan: showReview,
    suggest_activities: showSuggestions,
    confirm_preferences: showPreferencesConfirmation,
  }[data.step];
  const content = data.step === "done" ? showFinal(data) : draw(data.question);
  screenBox.replaceChildren(progress(data.step), ...content);
  if (scroll) screenBox.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- pezzi comuni

const TIME_FIELDS = ["fixed_start", "earliest_start", "deadline"];

const minutesOf = (hhmm) => {
  const [hours, minutes] = hhmm.split(":").map(Number);
  return hours * 60 + minutes;
};

// Il piano come linea del tempo: orari a sinistra, task a destra e, tra un task e l'altro,
// il tempo libero. La giornata si legge dall'alto in basso, come in un'agenda.
function timeline(scheduled) {
  if (!scheduled.length) return notice("info", t("no_tasks_in_plan"));
  const items = [];
  scheduled.forEach((slot, i) => {
    const gap = i > 0 ? minutesOf(slot.start) - minutesOf(scheduled[i - 1].end) : 0;
    if (gap > 0) {
      items.push(el("li", { class: "gap" },
        el("span", { class: "time" }),
        el("span", { text: t("free_time", { duration: durationText(gap) }) })));
    }
    items.push(el("li", { class: "slot" },
      el("span", { class: "time", text: `${slot.start}–${slot.end}` }),
      el("span", { class: "task" },
        el("strong", { text: slot.title }),
        el("span", { class: "length", text: durationText(minutesOf(slot.end) - minutesOf(slot.start)) }))));
  });
  return el("ol", { class: "timeline" }, ...items);
}

// unscheduled: false dove la domanda stessa parla dei task rimasti fuori (niente doppioni)
function showSchedule(plan, { unscheduled = true } = {}) {
  const parts = [timeline(plan.scheduled)];
  if (unscheduled && plan.unscheduled.length) {
    parts.push(notice("warning", t("left_out", { titles: plan.unscheduled.join(", ") })));
  }
  return parts;
}

function showWarnings(summary) {
  return summary.warnings.map((w) => notice("warning", w));
}

function showRejected(summary) {
  return summary.rejected.map((r) => notice("error", t("rejected", r)));
}

function showPlan(plan, options) {
  return [heading(t("day_plan")), ...showSchedule(plan, options), ...showWarnings(plan)];
}

const TASK_COLUMNS = ["col_title", "col_duration", "col_priority", "col_required", "col_start",
  "col_after", "col_before"];

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
  const view = table(TASK_COLUMNS.map((key) => t(key)), rows);
  const read = () => Object.fromEntries(Object.entries(inputs).map(([id, f]) => [id, {
    duration_min: f.duration_min.value === "" ? null : Number(f.duration_min.value),
    priority: Number(f.priority.value),
    required: f.required.checked,
    ...Object.fromEntries(TIME_FIELDS.map((k) => [k, f[k].value === "" ? null : f[k].value])),
  }]));
  return { view, read };
}

// Solo i campi cambiati: {"edits": {}} se niente è cambiato (l'editor del grafo applica il resto).
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
  const day = shortDate(saved.day_date);
  if (saved.replaced) return [notice("warning", t("saved_replaced", { day }))];
  return [
    notice("info", t("saved_merge", { day })),
    el("h3", { text: t("already_planned") }),
    caption(`«${saved.user_input}»`),
    ...showSchedule(saved),
  ];
}

function showConfirmation(question) {
  const parts = [heading(t("check_tasks"))];
  const saved = question.saved_day;
  if (saved) parts.push(...showSavedDay(saved), el("h3", { text: t("new_tasks") }));
  let read = () => ({});
  if (question.tasks.length) {
    parts.push(caption(t("check_hint")));
    const editor = editTable(question.tasks);
    parts.push(editor.view);
    read = editor.read;
  } else {
    parts.push(notice("info", t("no_tasks_found")));
  }
  parts.push(...showRejected(question), ...showWarnings(question));

  // un solo bottone di conferma: diffEdits capisce da solo se qualcosa è cambiato
  const confirm = button(t("confirm_and_plan"), (origin) =>
    answer(diffEdits(question.tasks, read()), "invalid_edits", origin), true);
  const replace = saved && !saved.replaced
    ? button(t("replace_saved"), (origin) =>
      answer({ ...diffEdits(question.tasks, read()), replace_saved: true }, "invalid_edits", origin))
    : null;
  parts.push(buttons(confirm, replace));
  return parts;
}

function showConflict(question) {
  const editor = editTable(question.tasks);
  return [
    heading(t("impossible_day")),
    notice("error", t("impossible_hint")),
    editor.view,
    ...showWarnings(question),
    // niente "continua senza modifiche": un piano impossibile non si può accettare
    buttons(button(t("try_again"), (origin) =>
      answer(diffEdits(question.tasks, editor.read()), "invalid_edits", origin), true)),
  ];
}

function showReview(plan) {
  // si arriva qui solo se qualche task non entra: è il motivo della domanda
  const missing = plan.unscheduled;
  return [
    ...showPlan(plan, { unscheduled: false }),
    // un messaggio solo, che è anche la domanda: niente "Non inseriti" ripetuto sopra
    el("div", { class: "alert warning" },
      el("strong", { text: missing.join(", ") }),
      ` ${t(missing.length === 1 ? "does_not_fit_one" : "does_not_fit_many")}`),
    buttons(
      button(t("continue_as_is"), (origin) => answer({ accept: true }, "invalid_answer", origin), true),
      button(t("edit_tasks"), (origin) => answer({ accept: false }, "invalid_answer", origin)),
    ),
  ];
}

// Prima i fatti, calcolati in Python; poi il commento del Critico, come opinione.
function showCritique(critique) {
  const longest = critique.longest_slot;
  const busy = t("busy_of", {
    busy: durationText(critique.busy_minutes),
    total: durationText(critique.total_minutes),
  });
  const parts = [
    el("div", { class: "metrics" },
      el("div", { class: "metric", title: t("busy_percent", { percent: critique.busy_percent }) },
        el("div", { class: "label", text: t("busy_time") }),
        el("div", { class: "value", text: busy })),
      el("div", { class: "metric" },
        el("div", { class: "label", text: t("longest_free") }),
        el("div", { class: "value", text: longest ? `${longest.start}–${longest.end}` : t("none") }))),
    caption(t("critic_comment")),
    notice("info", critique.assessment), // scritto dal modello, nella lingua scelta
  ];
  const considered = critique.recalled_preferences ?? [];
  if (considered.length) {
    parts.push(caption(t("considered", { list: considered.join("; ") })));
  } else if (state.database) {
    parts.push(caption(t("nothing_remembered_yet")));
  }
  return parts;
}

function showSuggestions(question) {
  const category = (name) => t("categories")[name] ?? name;
  return [
    ...showPlan(question.plan), // il piano su cui il Critico si esprime
    heading(t("critic")),
    ...showCritique(question),
    el("h3", { text: t("suggestions") }),
    // per ora non si possono aggiungere al piano (manca il passo nel grafo): dirlo, invece
    // di mostrare qualcosa che sembra cliccabile
    caption(t("suggestions_hint")),
    el("ul", { class: "suggestions" }, ...question.suggestions.map((s) => el("li", { class: "card" },
      el("div", { class: "row" },
        el("strong", { text: s.title }),
        el("span", { class: "caption", text: `${category(s.category)} · ${durationText(s.duration_min)}` })),
      el("p", { class: "caption", text: s.reason })))),
    ...showWarnings(question),
    buttons(button(t("continue"), (origin) => answer({ accepted: [] }, "invalid_answer", origin), true)),
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
      return el("label", { class: "check" }, box, t("delete_saved", { text: saved.text }));
    });
    return el("div", { class: "card" },
      el("label", { class: "check" }, keepBox, el("strong", { lang: "it", text: pref.text })),
      caption(`«${pref.source}»`),
      ...similar);
  });
  const chosen = (pairs) => pairs.filter(([, box]) => box.checked).map(([id]) => id);
  return [
    heading(t("preferences_found")),
    caption(t("preferences_hint")),
    ...cards,
    buttons(button(t("confirm"), (origin) =>
      answer({ keep: chosen(keep), delete: chosen(remove) }, "invalid_answer", origin), true)),
  ];
}

// L'esito, in cima al piano finale: è la cosa più importante, e il download è l'azione
// principale della schermata.
function showOutcome(result) {
  const saved = result.save_result;
  const parts = [];
  if (saved === null) {
    parts.push(notice("success", t("confirmed_no_db")));
  } else if (!saved.saved) {
    parts.push(notice("warning", `⚠️ ${saved.message}`)); // non salvato: va notato
  } else {
    parts.push(notice("success", `✅ ${saved.message}`));
    parts.push(el("div", { class: "buttons" }, el("a", {
      class: "button primary",
      href: `/days/${state.dayDate}/plan.ics`,
      text: t("download"),
    })));
  }
  // il passaggio delle preferenze si vede sempre, anche quando non c'era niente da chiedere
  if (result.preference_candidates !== null) {
    const message = result.preference_result?.message;
    if (message) parts.push(notice("info", `🧠 ${message}`));
    else if (result.preference_candidates === 0) parts.push(caption(t("no_preferences_in_sentence")));
    else parts.push(caption(t("nothing_remembered")));
  }
  return parts;
}

function showFinal(result) {
  const yes = (value) => (value ? "✓" : "");
  // salvato, il messaggio nomina già i task rimasti fuori: nel piano non si ripetono
  const unscheduled = !result.save_result?.saved;
  return [
    heading(t("plan_ready")),
    ...showOutcome(result),
    ...showPlan(result.plan, { unscheduled }),
    heading(t("critic")),
    ...showCritique(result.critique),
    // i dettagli servono a chi li cerca: chiusi, non allungano la pagina
    el("details", { class: "more" },
      el("summary", { text: t("task_details", { count: result.tasks.length }) }),
      // confermati non vuol dire inseriti: la prima colonna dice dove è finito ognuno
      table(
        ["col_slot", ...TASK_COLUMNS].map((key) => t(key)),
        result.tasks.map((task) => [task.slot ?? t("not_in_plan"), task.title, task.duration_min,
          task.priority, yes(task.required), task.fixed_start ?? "", task.earliest_start ?? "",
          task.deadline ?? ""]),
      ),
      ...showRejected(result)),
  ];
}

// ---------------------------------------------------------------- le finestre

// cosa ridisegnare in ogni finestra: lo storico è tutto da caricare, nelle impostazioni solo
// l'elenco delle preferenze (lingua e tema sono già nella pagina)
const FILL = {
  "history-dialog": [".dialog-body", fillHistory],
  "settings-dialog": ["#preferences-list", fillPreferences],
};

function openDialog(id) {
  const dialog = document.querySelector(`#${id}`);
  dialog.showModal(); // finestra modale: la chiudono Esc, la X e un clic sullo sfondo
  refill(dialog);
}

// Un clic sullo sfondo scuro chiude la finestra. Lo sfondo (::backdrop) fa parte del <dialog>,
// quindi il clic arriva al dialog stesso: si riconosce dal punto, fuori dal suo riquadro.
// Conta solo un clic cominciato e finito fuori: chi seleziona del testo dentro la finestra e
// rilascia il mouse fuori non la vede sparire.
function closeOnBackdrop(dialog) {
  const outside = (event) => {
    const box = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < box.left || event.clientX > box.right ||
      event.clientY < box.top || event.clientY > box.bottom);
  };
  let pressedOutside = false;
  dialog.addEventListener("pointerdown", (event) => (pressedOutside = outside(event)));
  dialog.addEventListener("click", (event) => {
    if (pressedOutside && outside(event)) dialog.close();
    pressedOutside = false;
  });
}

function refill(dialog) {
  const [selector, fill] = FILL[dialog.id];
  const body = dialog.querySelector(selector);
  body.replaceChildren(caption(t("loading")));
  fill(body);
}

async function fillHistory(body) {
  const result = await api("GET", "/days");
  if (!result.ok) {
    body.replaceChildren(notice("error", errorText(result.data.detail)));
    return;
  }
  if (!result.data.length) {
    body.replaceChildren(notice("info", t("no_saved_days")));
    return;
  }
  body.replaceChildren(...result.data.flatMap((day) => [
    el("p", {},
      el("strong", { text: longDate(day.day_date) }),
      ` · ${t("free_time_day", { duration: durationText(day.free_minutes) })} · `,
      el("a", { href: `/days/${day.day_date}/plan.ics`, text: "📥 .ics" })),
    caption(`«${day.user_input}»`),
    timeline(day.scheduled),
  ]));
}

async function fillPreferences(body) {
  if (!state.database) {
    body.replaceChildren(caption(t("preferences_need_db")));
    return;
  }
  const result = await api("GET", "/preferences");
  if (!result.ok) {
    body.replaceChildren(notice("error", errorText(result.data.detail)));
    return;
  }
  if (!result.data.length) {
    body.replaceChildren(notice("info", t("no_preferences")));
    return;
  }
  const remove = async (id) => {
    const deleted = await api("DELETE", `/preferences/${id}`);
    if (!deleted.ok) body.prepend(notice("error", errorText(deleted.data.detail)));
    else fillPreferences(body); // l'elenco ridisegnato è già senza la preferenza cancellata
  };
  body.replaceChildren(
    caption(t("preferences_list_hint")),
    ...result.data.map((pref) => {
      const seen = pref.times_seen === 1 ? t("seen_once") : t("seen_times", { count: pref.times_seen });
      const last = t("last_seen", { day: shortDate(pref.last_seen) });
      return el("div", { class: "card row" },
        el("div", {},
          el("strong", { lang: "it", text: pref.text }),
          caption(`${seen} · ${last} · «${pref.source}»`)),
        button(t("delete"), () => remove(pref.id), "danger"));
    }),
  );
}

function showToast(text) {
  const toast = document.querySelector("#toast");
  toast.textContent = text;
  toast.hidden = false;
  setTimeout(() => (toast.hidden = true), 5000); // scompare da solo
}

// Cosa dire di Ollama e dei modelli, o null se è tutto pronto.
function modelsNotice(health) {
  if (!health) return null;
  if (health.ollama === false) return ["warning", t("ollama_down")];
  for (const [model, status] of Object.entries(health.models ?? {})) {
    if (status.state === "error") return ["warning", t("model_error", { model, error: status.error })];
    if (status.state === "downloading") {
      return ["info", t("model_downloading", { model, percent: status.percent ?? 0 })];
    }
    if (status.state === "checking") return ["info", t("models_checking")];
  }
  return null;
}

function showModels() {
  const message = modelsNotice(state.health);
  document.querySelector("#models").replaceChildren(...(message ? [notice(...message)] : []));
}

// La prima volta i modelli si scaricano in sottofondo (minuti): finché non sono pronti, o
// Ollama non risponde, la pagina richiede /health ogni 3 secondi e aggiorna l'avviso;
// quando è tutto pronto l'avviso sparisce e la pagina smette di chiedere.
function watchModels() {
  showModels();
  if (!modelsNotice(state.health)) return;
  setTimeout(async () => {
    const health = await api("GET", "/health");
    if (health.ok) state.health = health.data;
    watchModels();
  }, 3000);
}

function showBanner(key) {
  state.bannerKey = key;
  document.querySelector("#banner").replaceChildren(notice("warning", t(key)));
}

// ---------------------------------------------------------------- tema chiaro / scuro

// "system": nessuna scelta salvata, il CSS segue il tema del sistema (prefers-color-scheme)
function themeChoice() {
  return document.documentElement.dataset.theme ?? "system";
}

function setTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  // localStorage: la scelta resta per le prossime aperture, solo in questo browser.
  // Può non esserci (finestra anonima, dati bloccati): allora vale solo fino alla chiusura
  try {
    if (choice === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", choice);
  } catch {
    // nessun problema: il tema è già applicato
  }
  markChoices();
}

// ---------------------------------------------------------------- avvio

async function start() {
  translateStatic();
  document.querySelectorAll("#language button").forEach((choice) =>
    choice.addEventListener("click", () => setLanguage(choice.dataset.language)));
  document.querySelectorAll("#theme button").forEach((choice) =>
    choice.addEventListener("click", () => setTheme(choice.dataset.themeChoice)));

  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  document.querySelector("#day").value = isoDate(tomorrow);

  form.addEventListener("submit", (event) => {
    event.preventDefault(); // niente ricarica: la richiesta la fa fetch, in JSON
    const text = document.querySelector("#text").value.trim();
    if (!text) {
      showError(t("empty_sentence"));
      return;
    }
    // event.submitter: il bottone che ha inviato il modulo (anche con Invio nel campo)
    const origin = event.submitter ?? document.querySelector("#new-plan button[type=submit]");
    startPlanning(text, document.querySelector("#day").value, origin);
  });
  document.querySelector("#open-history").addEventListener("click", () => openDialog("history-dialog"));
  document.querySelector("#open-settings").addEventListener("click", () =>
    openDialog("settings-dialog"));
  document.querySelectorAll("dialog .close").forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()));
  document.querySelectorAll("dialog").forEach(closeOnBackdrop);

  const health = await api("GET", "/health");
  state.database = health.ok && health.data.database;
  if (health.ok) {
    state.health = health.data;
    watchModels();
  }
  if (!health.ok) {
    showError(errorText(health.data.detail));
  } else if (!state.database) {
    showBanner("database_down");
  } else {
    document.querySelector("#actions").hidden = false; // senza database i bottoni non ci sono
    const purged = health.data.purged;
    if (purged) showToast(purged === 1 ? t("purged_one") : t("purged_many", { count: purged }));
  }
}

start();
