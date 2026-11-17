/* Golf tee sheet PWA. Plain JavaScript, no build step. Talks to /api/golf/* on the same origin
   (nginx relays it to the loopback API); the session is an HttpOnly cookie. Every action is a
   visible button with a data-action attribute, so it works the same with a finger or a mouse. */
(() => {
  "use strict";

  // ---------------------------------------------------------------- helpers
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const main = $("#main");
  const dialog = $("#sheet");
  const sheetForm = $("#sheet-form");

  const state = {
    course: null, today: null, user: null,
    view: "tee", arg: null,
    date: null, sheet: null, inventory: null, scrolledFor: null,
    me: null,
    playerQuery: "", players: [], player: null,
    products: null, settings: null,
  };

  const ICONS = {
    tee: '<path d="M7 21V3l10 4-10 4"/><path d="M4 21h10"/>',
    mine: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    counter: '<path d="M3 6h2l2.5 10h11L21 8H7"/><circle cx="9.5" cy="19.5" r="1.5"/><circle cx="17.5" cy="19.5" r="1.5"/>',
    players: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c1-3.5 3.5-5 6.5-5s5.5 1.5 6.5 5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.5c2.5 0 4.5 1.5 5.5 4.5"/>',
    setup: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    sun: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20.5V16h-4.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    clubs: '<path d="M7 3l7.5 14.5"/><path d="M14.5 17.5c1 1.6 3.4 2.4 5.5 1.5l-1-3.3-3.6.1"/>',
    pull: '<path d="M5 3l4 14"/><path d="M9 17h9"/><circle cx="9.5" cy="19.5" r="1.5"/><circle cx="17" cy="19.5" r="1.5"/><path d="M8 13h7l2-6H6.5"/>',
    cart: '<path d="M3 15V9a2 2 0 0 1 2-2h9l4 4h1.5a1.5 1.5 0 0 1 1.5 1.5V15"/><path d="M3 15h18"/><circle cx="7" cy="17.5" r="2"/><circle cx="17" cy="17.5" r="2"/><path d="M14 7V4h-4"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    seat: '<circle cx="12" cy="9" r="3.2"/><path d="M6.5 19c.9-3 3-4.5 5.5-4.5s4.6 1.5 5.5 4.5"/>',
  };
  const svg = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  const icon = (name) => svg(ICONS[name]);

  const initials = (name) => {
    const parts = String(name || "").replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  };
  const hueOf = (name) => [...String(name || "")].reduce((sum, ch) => (sum * 31 + ch.charCodeAt(0)) % 997, 7) % 6;
  const avatar = (name, { guest = false, checked = false, large = false } = {}) =>
    `<span class="avatar ${guest ? "guest" : `h${hueOf(name)}`} ${large ? "lg" : ""}" aria-hidden="true">${esc(initials(name))}${checked ? `<span class="tick">${icon("check")}</span>` : ""}</span>`;

  const tz = () => state.course?.time_zone || undefined;
  const fmtClock = (iso) => new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZone: tz() }).format(new Date(iso));
  const fmtWhen = (iso) => new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: tz() }).format(new Date(iso));
  const fmtStamp = (iso) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: tz() }).format(new Date(iso));
  const fmtSlot = (hhmm) => {
    const [h, m] = hhmm.split(":").map(Number);
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }).format(Date.UTC(2000, 0, 1, h, m));
  };
  const fmtSlotParts = (hhmm) => {
    const [h, m] = hhmm.split(":").map(Number);
    const parts = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }).formatToParts(Date.UTC(2000, 0, 1, h, m));
    const period = parts.find((p) => p.type === "dayPeriod")?.value || "";
    const time = parts.filter((p) => p.type !== "dayPeriod").map((p) => p.value).join("").trim();
    return { time, period };
  };
  const fmtDay = (ymd, style = "short") => new Intl.DateTimeFormat(undefined, style === "long"
    ? { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" }
    : { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(`${ymd}T12:00:00Z`));
  const fmtDate = (ymd) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${ymd}T12:00:00Z`));
  const addDays = (ymd, n) => { const d = new Date(`${ymd}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const money = (cents) => (cents == null ? "No price set" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(cents / 100));
  const roundLength = () => {
    const minutes = state.course?.average_round_minutes || 150;
    return `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
  };
  const clubsLabel = (clubs) => ({ right: "RH clubs", left: "LH clubs" })[clubs] || "";
  const isStaff = () => Boolean(state.user?.is_staff);

  async function api(path, { method = "GET", body } = {}) {
    const options = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (method !== "GET") options.headers["X-Golf-Client"] = "1";
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(`/api/golf${path}`, options);
    } catch {
      setOffline(true);
      throw new Error("You're offline. Check the connection and try again.");
    }
    setOffline(false);
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && state.user && !path.startsWith("/auth/")) {
      state.user = null;
      renderChrome();
    }
    if (!response.ok) throw Object.assign(new Error(data.error || `Request failed (${response.status})`), { status: response.status });
    return data;
  }

  function setOffline(offline) {
    $("#offline").hidden = !offline;
  }

  let toastTimer = 0;
  function toast(message, bad = false) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.toggle("bad", bad);
    node.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("show"), bad ? 5000 : 2800);
  }

  function showError(error) {
    const target = dialog.open ? $(".form-error", sheetForm) : null;
    if (target) target.textContent = error.message;
    else toast(error.message, true);
  }

  const button = (label, action, data = {}, kind = "") => {
    const { label: ariaLabel, ...rest } = data;
    const attrs = Object.entries(rest).map(([key, value]) => `data-${key}="${esc(value)}"`).join(" ");
    const aria = ariaLabel ? ` aria-label="${esc(ariaLabel)}" title="${esc(ariaLabel)}"` : "";
    const classes = kind.split(" ").filter(Boolean).map((k) => (k.includes("-") ? k : `btn-${k}`)).join(" ");
    return `<button class="btn ${classes}" type="button" data-action="${action}" ${attrs}${aria}>${label}</button>`;
  };

  // ---------------------------------------------------------------- dialog
  let sheetSubmit = null;
  let sheetState = {};

  function openSheet({ title, body, submit = "", danger = false, onSubmit = null, cancel = "Cancel", context = {} }) {
    sheetSubmit = onSubmit;
    sheetState = context;
    sheetForm.innerHTML = `
      <div class="grabber" aria-hidden="true"></div>
      <header class="sheet-head">
        <h2 id="sheet-title">${esc(title)}</h2>
        <button class="btn btn-icon" type="button" data-close aria-label="Close">${icon("close")}</button>
      </header>
      <div class="sheet-body">${body}</div>
      <p class="form-error" role="alert"></p>
      ${submit ? `<footer class="sheet-foot">
        ${cancel ? `<button class="btn" type="button" data-close>${esc(cancel)}</button>` : ""}
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="submit">${esc(submit)}</button>
      </footer>` : ""}`;
    if (!dialog.open) dialog.showModal();
    const first = $(".sheet-body input:not([type=radio]):not([type=checkbox]):not([type=hidden]), .sheet-body select, .sheet-body textarea", sheetForm);
    if (first && matchMedia("(pointer: fine)").matches) first.focus();
    else $(".sheet-head h2", sheetForm).setAttribute("tabindex", "-1");
  }

  function closeSheet() {
    if (dialog.open) dialog.close();
    sheetSubmit = null;
    sheetState = {};
  }

  sheetForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!sheetSubmit) return closeSheet();
    const submitButton = $("button[type=submit]", sheetForm);
    const error = $(".form-error", sheetForm);
    error.textContent = "";
    submitButton?.setAttribute("aria-busy", "true");
    if (submitButton) submitButton.disabled = true;
    try {
      const keepOpen = await sheetSubmit(sheetForm);
      if (keepOpen !== true) closeSheet();
    } catch (err) {
      error.textContent = err.message;
      error.scrollIntoView({ block: "nearest" });
    } finally {
      submitButton?.removeAttribute("aria-busy");
      if (submitButton) submitButton.disabled = false;
    }
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeSheet();
  });
  dialog.addEventListener("close", () => { sheetSubmit = null; });

  function confirmSheet(title, message, submit, onConfirm, danger = true) {
    openSheet({ title, body: `<p>${message}</p>`, submit, danger, onSubmit: onConfirm, cancel: "Keep it" });
  }

  // ---------------------------------------------------------------- shared form pieces
  let fieldSeq = 0;

  function optionsEditor(key, { clubs = "none", pull_cart = false } = {}) {
    const id = `clubs-label-${key}`;
    return `<div class="options">
      <div class="field">
        <span class="label" id="${id}">Rental clubs</span>
        <div class="seg" role="radiogroup" aria-labelledby="${id}">
          ${[["none", "None"], ["right", "Right-hand"], ["left", "Left-hand"]].map(([value, label]) =>
            `<label><input type="radio" name="clubs-${key}" value="${value}" ${clubs === value ? "checked" : ""}><span>${label}</span></label>`).join("")}
        </div>
      </div>
      <label class="toggle"><input type="checkbox" name="pull-${key}" ${pull_cart ? "checked" : ""}><span>Pull cart</span></label>
    </div>`;
  }

  const readOptions = (form, key) => ({
    clubs: form.elements[`clubs-${key}`]?.value || "none",
    pull_cart: Boolean(form.elements[`pull-${key}`]?.checked),
  });

  function partyRow({ kind, name = "", playerId = "", removable = true, note = "" }) {
    const key = `p${++fieldSeq}`;
    const who = kind === "guest"
      ? `<label class="field"><span class="label">Player name (optional)</span><input type="text" name="name-${key}" maxlength="80" autocomplete="off" autocapitalize="words" placeholder="Guest" value="${esc(name)}"></label>`
      : `<div>${avatar(name)}<span><strong>${esc(name)}</strong>${note ? `<span class="hint">${esc(note)}</span>` : ""}</span></div>`;
    return `<div class="party-row" data-key="${key}" data-kind="${kind}" ${playerId ? `data-player-id="${esc(playerId)}"` : ""}>
      <div class="party-who">${who}${removable ? button("Remove", "remove-row", {}, "quiet") : ""}</div>
      ${optionsEditor(key)}
    </div>`;
  }

  function readParty(form) {
    return $$(".party-row", form).map((row, index) => {
      const key = row.dataset.key;
      const options = readOptions(form, key);
      if (row.dataset.kind === "player") return { player_id: Number(row.dataset.playerId), ...options };
      if (row.dataset.kind === "guest") {
        // Names are optional so a quick "3 players" booking needs no typing.
        const name = form.elements[`name-${key}`].value.trim() || `Guest ${index + 1}`;
        return { name, ...options };
      }
      return { me: true, ...options };
    });
  }

  function stepper(name, value, min, max, label) {
    return `<div class="stepper" data-stepper>
      ${button("−", "step", { step: -1 }, "icon")}
      <input type="number" name="${name}" inputmode="numeric" min="${min}" max="${max}" value="${value}" aria-label="${esc(label)}">
      ${button("+", "step", { step: 1 }, "icon")}
    </div>`;
  }

  // Big one-tap number choices (1 2 3 4) instead of +/- steppers.
  function choiceSeg(name, options, value, labelledBy, action = "") {
    return `<div class="seg seg-count" role="radiogroup" aria-labelledby="${labelledBy}" id="${name}-seg">${options.map(([optionValue, label]) =>
      `<label><input type="radio" name="${name}" value="${optionValue}" ${String(optionValue) === String(value) ? "checked" : ""} ${action ? `data-action="${action}"` : ""}><span>${label}</span></label>`).join("")}</div>`;
  }
  const ridingOptions = (max) => Array.from({ length: max + 1 }, (_, n) => [n, n === 0 ? "None" : String(n)]);
  const countOptions = (max) => Array.from({ length: max }, (_, i) => [i + 1, String(i + 1)]);

  function pickerField(id, label) {
    return `<div class="picker" data-picker="${id}">
      <label class="field"><span class="label">${esc(label)}</span>
        <input type="search" data-picker-input="${id}" placeholder="Search by name, email or phone" autocomplete="off" enterkeyhint="search">
      </label>
      <div class="picker-results" id="picker-${id}"></div>
    </div>`;
  }

  let pickerTimer = 0;
  // Enter in a player search runs the search; it must never submit the sheet behind it.
  sheetForm.addEventListener("keydown", (event) => {
    const input = event.target.closest?.("[data-picker-input]");
    if (event.key !== "Enter" || !input) return;
    event.preventDefault();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  sheetForm.addEventListener("input", (event) => {
    const input = event.target.closest("[data-picker-input]");
    if (!input) return;
    clearTimeout(pickerTimer);
    pickerTimer = setTimeout(async () => {
      const id = input.dataset.pickerInput;
      const results = $(`#picker-${id}`, sheetForm);
      const q = input.value.trim();
      if (!q) { results.innerHTML = ""; return; }
      try {
        const { players } = await api(`/players?q=${encodeURIComponent(q)}`);
        results.innerHTML = players.length ? players.slice(0, 6).map((p) => `
          <button class="list-item" type="button" data-action="pick" data-picker="${id}" data-id="${p.id}" data-name="${esc(p.full_name)}">
            ${avatar(p.full_name)}<span><strong>${esc(p.full_name)}</strong>
            <small>${esc([p.email, p.phone].filter(Boolean).join(" · ") || "No contact details")}${p.active_passes ? ` · ${plural(p.active_passes, "active pass", "active passes")}` : ""}</small></span>
          </button>`).join("") : `<p class="hint">No players match “${esc(q)}”.</p>`;
      } catch (error) {
        results.innerHTML = `<p class="hint">${esc(error.message)}</p>`;
      }
    }, 250);
  });

  // ---------------------------------------------------------------- theme
  const THEME_KEY = "golf-theme";
  const THEME_NAMES = { system: "Match device", light: "Light", dark: "Dark" };
  const THEME_COLOURS = { light: "#f4f8f4", dark: "#0c120f" };
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");

  function themeChoice() {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  }

  const effectiveTheme = (choice = themeChoice()) => (choice === "system" ? (darkQuery.matches ? "dark" : "light") : choice);

  function applyTheme(choice) {
    try {
      if (choice === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, choice);
    } catch {
      // Private browsing can block storage; the choice still applies until the page closes.
    }
    if (choice === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = choice;
    renderThemeButton(choice);
  }

  function renderThemeButton(choice = document.documentElement.dataset.theme || themeChoice()) {
    const effective = effectiveTheme(choice);
    const themeButton = $("#theme-button");
    themeButton.innerHTML = svg(effective === "dark" ? ICONS.moon : ICONS.sun);
    const label = `Theme: ${THEME_NAMES[choice]}${choice === "system" ? ` (${effective})` : ""}`;
    themeButton.setAttribute("aria-label", `${label}. Change theme`);
    themeButton.title = label;
    $$('meta[name="theme-color"]').forEach((meta) => meta.setAttribute("content", THEME_COLOURS[effective]));
  }

  function openTheme() {
    const choice = document.documentElement.dataset.theme || themeChoice();
    openSheet({
      title: "Appearance",
      body: `<div class="choices" role="radiogroup" aria-label="Theme">${[
        ["system", "Follows your device's light or dark setting"],
        ["light", "Easiest to read in bright sun"],
        ["dark", "Easier on the eyes indoors and at night"],
      ].map(([value, detail]) => `<label class="choice"><input type="radio" name="theme" value="${value}" data-action="set-theme" ${choice === value ? "checked" : ""}>
        <span><b>${THEME_NAMES[value]}</b><small>${detail}</small></span></label>`).join("")}</div>
        <p class="hint">Saved on this device.</p>`,
      submit: "Done", cancel: "",
    });
  }

  darkQuery.addEventListener?.("change", () => renderThemeButton());

  function applyFills(root) {
    $$("[data-fill]", root).forEach((el) => { el.style.width = `${clamp(Number(el.dataset.fill) || 0, 0, 100)}%`; });
  }

  // ---------------------------------------------------------------- chrome and routing
  const VIEWS = {
    tee: { label: "Tee sheet", load: loadTee, render: renderTee },
    mine: { label: "My golf", load: loadMine, render: renderMine, needs: "user" },
    counter: { label: "Counter", load: loadCounter, render: renderCounter, needs: "staff" },
    players: { label: "Players", load: loadPlayers, render: renderPlayers, needs: "staff" },
    setup: { label: "Setup", load: loadSetup, render: renderSetup, needs: "staff" },
  };

  const allowed = (view) => !VIEWS[view].needs || (VIEWS[view].needs === "user" ? Boolean(state.user) : isStaff());

  function renderChrome() {
    $("#course-name").textContent = state.course?.course_name || "Tee Sheet";
    $("#today-label").textContent = state.today ? fmtDay(state.today, "long") : "";
    document.title = `${VIEWS[state.view]?.label || "Tee sheet"} · ${state.course?.course_name || "Golf"}`;
    const account = $("#account-button");
    account.innerHTML = state.user ? avatar(state.user.full_name) : "Sign in";
    account.classList.toggle("has-avatar", Boolean(state.user));
    account.setAttribute("aria-label", state.user ? `Account: ${state.user.full_name}` : "Sign in or create an account");
    $("#tabs").innerHTML = Object.entries(VIEWS).filter(([view]) => allowed(view)).map(([view, info]) => `
      <button class="tab" type="button" data-action="go" data-view="${view}" ${state.view === view ? 'aria-current="page"' : ""}>
        <span class="tab-icon">${svg(ICONS[view])}</span><span>${info.label}</span>
      </button>`).join("");
  }

  function parseHash() {
    const [view, arg] = location.hash.replace(/^#\/?/, "").split("/");
    return { view: VIEWS[view] ? view : "tee", arg: arg ? decodeURIComponent(arg) : null };
  }

  function go(view, arg = null) {
    const hash = `#${view}${arg ? `/${encodeURIComponent(arg)}` : ""}`;
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  let routeToken = 0;
  async function route() {
    let { view, arg } = parseHash();
    if (!allowed(view)) { view = "tee"; arg = null; }
    const token = ++routeToken;
    const changed = view !== state.view;
    state.view = view;
    state.arg = arg;
    renderChrome();
    if (changed || !main.dataset.view) main.innerHTML = '<p class="loading">Loading…</p>';
    try {
      await VIEWS[view].load(arg);
      if (token !== routeToken) return;
      main.dataset.view = view;
      VIEWS[view].render();
    } catch (error) {
      if (token !== routeToken) return;
      main.innerHTML = `<div class="error-panel"><p>${esc(error.message)}</p>${button("Try again", "retry", {}, "primary")}</div>`;
    }
  }

  async function reload() {
    const y = window.scrollY;
    await VIEWS[state.view].load(state.arg);
    VIEWS[state.view].render();
    window.scrollTo(0, y);
  }

  // ---------------------------------------------------------------- tee sheet
  async function loadTee(date) {
    state.date = date || state.date || state.today;
    const [sheet, inventory] = await Promise.all([
      api(`/tee-sheet?date=${encodeURIComponent(state.date)}`),
      api("/inventory").catch(() => null),
    ]);
    state.sheet = sheet;
    state.inventory = inventory;
  }

  const KIND_ICON = { riding_cart: "cart", pull_cart: "pull", club_set: "clubs" };

  function statCard(iconName, value, total, label, warn = false) {
    return `<div class="stat ${warn ? "warn" : ""}"><span class="stat-icon">${icon(iconName)}</span>
      <b>${value}${total != null ? `<small> / ${total}</small>` : ""}</b><span>${esc(label)}</span></div>`;
  }

  function availabilityStats() {
    if (!state.inventory) return "";
    return state.inventory.groups.filter((g) => g.total || g.out).map((g) => {
      const name = { riding_cart: "Riding carts", pull_cart: "Pull carts", club_set_right: "RH club sets", club_set_left: "LH club sets" }[g.key] || g.name;
      return statCard(KIND_ICON[g.kind] || "cart", g.available, g.total, g.overdue ? `${name} free · ${g.overdue} overdue` : `${name} free now`, g.overdue > 0);
    }).join("");
  }

  function dayStrip(sheet) {
    const span = Math.max(7, Math.min(sheet.booking_window_days, 21));
    const days = Array.from({ length: span + 1 }, (_, i) => addDays(sheet.today, i));
    if (!days.includes(sheet.date)) (sheet.date < sheet.today ? days.unshift(sheet.date) : days.push(sheet.date));
    return days.map((ymd) => {
      const d = new Date(`${ymd}T12:00:00Z`);
      const weekday = new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: "UTC" }).format(d);
      const label = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" }).format(d);
      return `<button class="day ${ymd === sheet.today ? "is-today" : ""}" type="button" data-action="set-day" data-date="${ymd}"
        ${ymd === sheet.date ? 'aria-current="date"' : ""} aria-label="${esc(label)}${ymd === sheet.today ? ", today" : ""}">
        <small>${esc(ymd === sheet.today ? "Today" : weekday)}</small><b>${d.getUTCDate()}</b></button>`;
    }).join("");
  }

  function renderTee() {
    const sheet = state.sheet;
    const openTimes = sheet.slots.filter((slot) => slot.bookable).length;
    const openSpots = sheet.slots.reduce((sum, slot) => sum + (slot.booking && !slot.past ? slot.booking.open_spots : 0), 0);
    main.innerHTML = `
      <div class="tee-top">
        <div><p class="eyebrow">${esc(fmtDay(sheet.date, "long"))}</p><h1>Tee sheet</h1></div>
        <div class="actions">
          <input type="date" class="date-native" id="date-input" value="${sheet.date}" tabindex="-1" aria-hidden="true">
          ${button(icon("calendar"), "pick-date", { label: "Choose a date" }, "icon")}
          ${button(icon("refresh"), "refresh", { label: "Refresh" }, "icon")}
        </div>
      </div>
      <nav class="days" aria-label="Choose a day">${dayStrip(sheet)}</nav>
      <div class="stats">
        ${state.user ? statCard("clock", openTimes, null, "Open tee times") + statCard("seat", openSpots, null, "Spots in groups") : ""}
        ${availabilityStats()}
      </div>
      ${state.user ? "" : `<div class="callout"><p>Sign in to book tee times, join groups and reserve rental clubs or pull carts.</p>${button("Sign in", "account", {}, "primary")}</div>`}
      <ol class="slots" aria-label="Tee times">${sheet.slots.map(renderSlot).join("")}</ol>`;
    $("#date-input").addEventListener("change", (event) => {
      if (event.target.value) setDate(event.target.value);
    });
    $(".day[aria-current]", main)?.scrollIntoView({ block: "nearest", inline: "center" });
    if (sheet.date === sheet.today && state.scrolledFor !== sheet.date) {
      state.scrolledFor = sheet.date;
      const next = $(".slot:not(.is-past)", main);
      if (next && next !== $(".slot", main)) next.scrollIntoView({ block: "center" });
    }
  }

  function renderSlot(slot) {
    const booking = slot.booking;
    const staff = isStaff();
    const actions = [];
    let seats = "";
    const meta = [];
    if (booking) {
      seats = booking.players.map((player) => playerChip(player, booking)).join("")
        + `<span class="seat-open" aria-hidden="true">${icon("plus")}</span>`.repeat(booking.open_spots);
      if (booking.open_spots) meta.push(`<span class="open-note">${plural(booking.open_spots, "open spot")}</span>`);
      if (booking.riding_carts) {
        const labels = booking.riding_cart_labels?.length ? ` · ${booking.riding_cart_labels.join(", ")}` : "";
        meta.push(`<span class="tag">${icon("cart")}${plural(booking.riding_carts, "riding cart")}${esc(labels)}</span>`);
      }
      if (booking.can_join && !staff) actions.push(button("Join", "join", { booking: booking.id }, "primary"));
      if (booking.is_member || staff) actions.push(button("Edit", "slot", { time: slot.time, label: `Edit the ${fmtSlot(slot.time)} booking` }, "tonal"));
      if (booking.can_cancel) actions.push(button("Cancel", "cancel-booking", { booking: booking.id, label: "Cancel this tee time" }, "danger"));
      else if (booking.can_leave) actions.push(button("Cancel", "leave", { booking: booking.id, label: cancelsWholeTeeTime(booking) ? "Cancel this tee time" : "Cancel my booking" }, "danger"));
    } else {
      seats = "";
      meta.push(`<span class="open-note">${slot.past ? "Not booked" : "Open · 4 spots"}</span>`);
      if (slot.bookable) actions.push(button("Book", "book", { time: slot.time }, "primary"));
      else if (!state.user && !slot.past) actions.push(button("Sign in to book", "account", {}, "tonal"));
    }
    const { time, period } = fmtSlotParts(slot.time);
    const classes = ["slot", booking ? "is-booked" : "is-open", slot.past ? "is-past" : "", booking?.is_member ? "is-mine" : ""].join(" ");
    return `<li class="${classes}" id="slot-${slot.time.replace(":", "")}" data-action="slot" data-time="${slot.time}">
      <button class="slot-time" type="button" data-action="slot" data-time="${slot.time}" aria-label="${esc(fmtSlot(slot.time))}: see options">
        <span class="t">${esc(time)}</span>${period ? `<span class="ampm">${esc(period)}</span>` : ""}${booking?.is_member ? '<span class="mine">Your group</span>' : ""}</button>
      <div class="slot-main">${seats ? `<div class="seats">${seats}</div>` : ""}<div class="slot-meta">${meta.join("")}</div></div>
      <div class="slot-actions">${actions.join("")}</div>
    </li>`;
  }

  function playerChip(player, booking) {
    const bits = [];
    if (player.is_guest && state.user) bits.push("<span>Guest</span>");
    if (clubsLabel(player.clubs)) bits.push(`<span class="mini">${icon("clubs")}${clubsLabel(player.clubs)}</span>`);
    if (player.pull_cart) bits.push(`<span class="mini">${icon("pull")}Pull cart</span>`);
    if (player.checked_in) bits.push("<span>Checked in</span>");
    if (isStaff() && player.gear?.length) bits.push(`<span>${esc(player.gear.join(", "))}</span>`);
    const content = `${avatar(player.name, { guest: player.is_guest || !state.user, checked: player.checked_in })}
      <span class="pchip-text">
        <span class="who">${esc(player.name)}${player.is_me ? " (you)" : ""}${player.is_captain && state.user ? " ★" : ""}</span>
        ${bits.length ? `<span class="meta">${bits.join("")}</span>` : ""}
      </span>`;
    const classes = `pchip ${player.checked_in ? "is-in" : ""} ${player.is_guest ? "is-guest" : ""}`;
    const actionable = isStaff() || player.can_edit || player.can_remove;
    return actionable
      ? `<button class="${classes}" type="button" data-action="player" data-booking="${booking.id}" data-player="${player.id}" aria-label="${esc(player.name)}: options">${content}</button>`
      : `<span class="${classes}">${content}</span>`;
  }

  function findBooking(id) {
    for (const slot of state.sheet.slots) {
      if (slot.booking && slot.booking.id === Number(id)) return { slot, booking: slot.booking };
    }
    throw new Error("That group has changed. Refresh and try again.");
  }

  function findPlayer(bookingId, playerId) {
    const { slot, booking } = findBooking(bookingId);
    const player = booking.players.find((p) => p.id === Number(playerId));
    if (!player) throw new Error("That player has left the group. Refresh and try again.");
    return { slot, booking, player };
  }

  // The people "Cancel" removes for a player: themselves and the guests they booked. When that is
  // the whole group, cancelling frees the tee time; golfers who joined on their own keep their spots.
  const myParty = (booking) => booking.players.filter((p) => p.is_me || (p.is_guest && p.can_remove && !isStaff()));
  const cancelsWholeTeeTime = (booking) => booking.is_member && myParty(booking).length === booking.players.length;
  const nameList = (names) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0] || "");

  function setDate(date) {
    state.date = date;
    history.replaceState(null, "", `#tee/${date}`);
    state.arg = date;
    route();
  }

  function whenText(slot) {
    return `${fmtDay(state.sheet.date, "long")} · ${fmtSlot(slot.time)}`;
  }

  function openBook(time) {
    if (!state.user) return openAccount();
    const slot = state.sheet.slots.find((s) => s.time === time);
    const staff = isStaff();
    openSheet({
      title: "Book a tee time",
      context: { captain: null, maxRows: 4 },
      body: `
        <p class="lede">${esc(whenText(slot))}</p>
        ${staff ? `${pickerField("captain", "Booking for (leave empty to book for yourself)")}<p class="hint" id="captain-note">Booking for: you</p>` : ""}
        <div class="field"><span class="label" id="size-label">Players</span>${choiceSeg("party-size", countOptions(4), 1, "size-label", "party-size")}</div>
        <div class="party" id="party">${partyRow({ kind: "me", name: staff ? "Lead player" : `${state.user.full_name} (you)`, removable: false })}</div>
        ${staff ? `<div class="row">${button(`${icon("plus")}Add from player list`, "add-known", {}, "tonal")}</div>` : ""}
        <div class="field"><span class="label" id="riding-label">Riding carts</span>${choiceSeg("riding", ridingOptions(1), 0, "riding-label")}</div>
        <p class="hint">Each player can choose rental clubs and a pull cart. Rentals are held from the tee time for ${esc(roundLength())}.</p>`,
      submit: "Book tee time",
      onSubmit: async (form) => {
        const [me, ...guests] = readParty(form);
        const body = {
          date: state.sheet.date, time,
          captain: { clubs: me.clubs, pull_cart: me.pull_cart },
          guests, riding_carts: Number(form.elements.riding.value) || 0,
        };
        if (sheetState.captain) body.captain_player_id = sheetState.captain.id;
        await api("/bookings", { method: "POST", body });
        toast(`Booked ${fmtSlot(time)}`);
        await reload();
      },
    });
    if (staff) {
      sheetState.onPick = {
        captain: ({ id, name }) => {
          if ($(`.party-row[data-player-id="${id}"]`, sheetForm)) throw new Error(`${name} is already in this list.`);
          sheetState.captain = { id, name };
          $("#captain-note", sheetForm).textContent = `Booking for: ${name}`;
          $(".party-row strong", sheetForm).textContent = name;
          $(".party-row .avatar", sheetForm).outerHTML = avatar(name);
        },
      };
    }
  }

  function openJoin(bookingId, staffAdd) {
    const { slot, booking } = findBooking(bookingId);
    const room = booking.open_spots;
    openSheet({
      title: staffAdd ? "Add players" : "Join this group",
      context: { maxRows: room, staffAdd },
      body: `
        <p class="lede">${esc(whenText(slot))}</p>
        <div class="field"><span class="label" id="size-label">${staffAdd ? "Players to add" : "How many of you, including you?"}</span>
          ${choiceSeg("party-size", countOptions(room), 1, "size-label", "party-size")}</div>
        <div class="party" id="party">${staffAdd ? partyRow({ kind: "guest", removable: false }) : partyRow({ kind: "me", name: `${state.user.full_name} (you)`, removable: false })}</div>
        ${staffAdd ? `<div class="row">${button(`${icon("plus")}Add from player list`, "add-known", {}, "tonal")}</div>` : ""}
        <p class="hint">${plural(room, "open spot")}. Rentals are held for ${esc(roundLength())} from the tee time.</p>`,
      submit: staffAdd ? "Add to group" : "Join group",
      onSubmit: async (form) => {
        const rows = readParty(form);
        const body = staffAdd
          ? { include_me: false, guests: rows }
          : { me: { clubs: rows[0].clubs, pull_cart: rows[0].pull_cart }, guests: rows.slice(1) };
        if (staffAdd && !rows.length) throw new Error("Add at least one player.");
        await api(`/bookings/${bookingId}/join`, { method: "POST", body });
        toast(staffAdd ? "Players added" : "You're in the group");
        await reload();
      },
    });
  }

  // Everything you can do with one tee time, from a tap anywhere on its row.
  function openSlot(time) {
    const slot = state.sheet.slots.find((s) => s.time === time);
    if (!slot) return;
    const booking = slot.booking;
    const staff = isStaff();
    const actions = [];
    let body;
    if (!booking) {
      body = `<div class="seats big">${`<span class="seat-open" aria-hidden="true">${icon("plus")}</span>`.repeat(4)}</div>
        <p>${slot.past ? "Nobody played this tee time." : "All four spots are open."}</p>`;
      if (slot.bookable) actions.push(button("Book this tee time", "book", { time }, "primary"));
      else if (!state.user && !slot.past) actions.push(button("Sign in to book", "account", {}, "primary"));
    } else {
      const rows = booking.players.map((player) => {
        const bits = [player.is_guest && state.user ? "Guest" : "", clubsLabel(player.clubs), player.pull_cart ? "Pull cart" : "",
          player.checked_in ? "Checked in" : ""].filter(Boolean);
        const inner = `${avatar(player.name, { guest: player.is_guest || !state.user, checked: player.checked_in })}
          <span><strong>${esc(player.name)}${player.is_me ? " (you)" : ""}${player.is_captain && state.user ? " ★" : ""}</strong>
          <small>${esc(bits.join(" · ") || (state.user ? "No rentals" : "Booked"))}</small></span>`;
        return staff || player.can_edit || player.can_remove
          ? `<button class="list-item" type="button" data-action="player" data-booking="${booking.id}" data-player="${player.id}">${inner}</button>`
          : `<div class="list-item plain">${inner}</div>`;
      }).join("");
      const open = `<div class="list-item plain"><span class="seat-open" aria-hidden="true">${icon("plus")}</span><span><strong>${plural(booking.open_spots, "open spot")}</strong></span></div>`;
      body = `<div class="list">${rows}${booking.open_spots ? open : ""}</div>
        ${booking.riding_carts ? `<p><span class="tag">${icon("cart")}${plural(booking.riding_carts, "riding cart")}${esc(booking.riding_cart_labels?.length ? ` · ${booking.riding_cart_labels.join(", ")}` : "")}</span></p>` : ""}`;
      const me = booking.players.find((player) => player.is_me);
      if (booking.can_join && !staff) actions.push(button("Join this group", "join", { booking: booking.id }, "primary"));
      if (me?.can_edit) actions.push(button("Edit my rentals", "player", { booking: booking.id, player: me.id }, "primary"));
      if (staff && booking.open_spots && (!slot.past || state.sheet.date === state.sheet.today)) actions.push(button(`${icon("plus")}Add players`, "add-players", { booking: booking.id }, me?.can_edit ? "tonal" : "primary"));
      if (booking.can_manage_carts) actions.push(button(`${icon("cart")}Riding carts`, "carts", { booking: booking.id }, "tonal"));
      if (booking.can_cancel) actions.push(button("Cancel this tee time", "cancel-booking", { booking: booking.id }, "danger"));
      else if (booking.can_leave) actions.push(button(cancelsWholeTeeTime(booking) ? "Cancel this tee time" : "Cancel my booking", "leave", { booking: booking.id }, "danger"));
    }
    openSheet({
      title: `${fmtSlot(time)} tee time`,
      body: `<p class="lede">${esc(fmtDay(state.sheet.date, "long"))}${slot.past ? " · already started" : ""}</p>
        ${body}${actions.length ? `<div class="sheet-actions">${actions.join("")}</div>` : ""}`,
    });
  }

  function openPlayer(bookingId, playerId) {
    const { slot, booking, player } = findPlayer(bookingId, playerId);
    const staff = isStaff();
    const coverage = { membership: "membership", punch_card: "punch card", pay_at_counter: "pay at the counter" }[player.coverage];
    openSheet({
      title: player.name,
      context: { bookingId, playerId },
      body: `
        <p class="lede">${esc(whenText(slot))}</p>
        ${player.can_edit ? optionsEditor("p", player) : `<p>${esc([clubsLabel(player.clubs), player.pull_cart ? "Pull cart" : ""].filter(Boolean).join(" · ") || "No rentals")}</p>`}
        ${staff && player.gear?.length ? `<p class="hint">Reserved: ${esc(player.gear.join(", "))}</p>` : ""}
        ${staff ? `<div class="card stack">
          <p><b>${player.checked_in ? "Checked in" : "Not checked in yet"}</b>${coverage ? ` · ${esc(coverage)}` : ""}</p>
          <div class="row">${player.checked_in ? button("Undo check-in", "undo-check-in", { booking: bookingId, player: playerId }) : button("Check in", "check-in", { booking: bookingId, player: playerId }, "primary")}
          ${player.player_id ? button("Player record", "open-player", { id: player.player_id }) : ""}</div>
        </div>` : ""}
        ${player.can_remove ? `<div>${button("Remove from group", "remove-player", { booking: bookingId, player: playerId }, "danger")}</div>` : ""}`,
      submit: player.can_edit ? "Save rentals" : "",
      onSubmit: player.can_edit ? async (form) => {
        await api(`/booking-players/${playerId}`, { method: "PUT", body: readOptions(form, "p") });
        toast("Rentals updated");
        await reload();
      } : null,
    });
  }

  function openCarts(bookingId) {
    const { slot, booking } = findBooking(bookingId);
    const players = booking.players.length;
    openSheet({
      title: "Riding carts",
      body: `
        <p class="lede">${esc(whenText(slot))}</p>
        <div class="field"><span class="label" id="carts-label">Riding carts for this group</span>${choiceSeg("count", ridingOptions(players), booking.riding_carts || 0, "carts-label")}</div>
        <p class="hint">Up to one cart per player. Carts are held for ${esc(roundLength())} from the tee time.</p>`,
      submit: "Save carts",
      onSubmit: async (form) => {
        await api(`/bookings/${bookingId}/riding-carts`, { method: "PUT", body: { count: Number(form.elements.count.value) || 0 } });
        toast("Riding carts updated");
        await reload();
      },
    });
  }

  async function openCheckIn(bookingId, playerId) {
    const { slot, player } = findPlayer(bookingId, playerId);
    const passesFor = async (id) => (id ? (await api(`/players/${id}`)).passes.filter((p) => p.status === "active" && p.covers !== "range") : []);
    const choices = (passes) => `
      ${passes.map((p) => `<label class="choice"><input type="radio" name="coverage" value="${p.kind}:${p.id}" ${p.state === "active" ? "" : "disabled"}>
        <span><b>${esc(p.name)}</b><small>${esc(passDetail(p))}${p.state === "active" ? "" : ` · ${passStateLabel(p.state)}`}</small></span></label>`).join("")}
      <label class="choice"><input type="radio" name="coverage" value="pay_at_counter" ${passes.some((p) => p.state === "active") ? "" : "checked"}>
        <span><b>Pay at the counter</b><small>Recorded as an unbilled green fee</small></span></label>`;
    const passes = await passesFor(player.player_id);
    const firstActive = passes.find((p) => p.state === "active");
    openSheet({
      title: `Check in ${player.name}`,
      context: { link: null },
      body: `
        <p class="lede">${esc(whenText(slot))}</p>
        ${player.player_id ? "" : `<div class="card stack">
          <p>${esc(player.name)} is a guest without a player record. Link them to use a pass or keep their history.</p>
          ${pickerField("link", "Find their player record")}
          <label class="toggle"><input type="checkbox" name="create_player"><span>Create a player record for ${esc(player.name)}</span></label>
          <p class="hint" id="link-note"></p>
        </div>`}
        <div class="field"><span class="label">How is this round covered?</span><div class="choices" id="coverage">${choices(passes)}</div></div>`,
      submit: "Check in",
      onSubmit: async (form) => {
        const value = form.elements.coverage.value;
        if (!value) throw new Error("Choose how the round is covered.");
        const [coverage, passId] = value.split(":");
        const body = { coverage };
        if (passId) body.pass_id = Number(passId);
        if (sheetState.link) body.link_player_id = sheetState.link.id;
        else if (form.elements.create_player?.checked) body.create_player = true;
        await api(`/booking-players/${playerId}/check-in`, { method: "POST", body });
        toast(`${player.name} checked in`);
        await reload();
      },
    });
    if (firstActive) {
      const radio = $$("input[name=coverage]", sheetForm).find((input) => input.value === `${firstActive.kind}:${firstActive.id}`);
      if (radio) radio.checked = true;
    }
    sheetState.onPick = {
      link: async ({ id, name }) => {
        sheetState.link = { id, name };
        $("#link-note", sheetForm).textContent = `Linked to ${name}.`;
        $("#coverage", sheetForm).innerHTML = choices(await passesFor(id));
      },
    };
  }

  // ---------------------------------------------------------------- my golf
  async function loadMine() {
    state.me = await api("/me");
  }

  const passStateLabel = (s) => ({ active: "Active", expired: "Expired", upcoming: "Not started", used_up: "Used up", void: "Void" })[s] || s;
  const coversLabel = (c) => ({ round: "Rounds", range: "Range buckets", round_and_range: "Rounds and range buckets" })[c] || c;

  function passDetail(p) {
    const parts = [];
    if (p.kind === "punch_card") parts.push(`${p.punches_remaining} of ${p.punches_total} left`);
    else parts.push(p.daily_round_limit ? `${plural(p.daily_round_limit, "round")} a day` : "Unlimited golf");
    parts.push(coversLabel(p.covers));
    parts.push(p.valid_until ? `${fmtDate(p.valid_from)} – ${fmtDate(p.valid_until)}` : `From ${fmtDate(p.valid_from)}, no expiry`);
    return parts.join(" · ");
  }

  function passCard(p, actions = "") {
    const off = p.state !== "active" && p.state !== "upcoming";
    let balance;
    if (p.kind === "punch_card") {
      const used = p.punches_total - p.punches_remaining;
      const holes = p.punches_total <= 20
        ? `<div class="punches" role="img" aria-label="${p.punches_remaining} of ${p.punches_total} punches left">${'<span class="punch"></span>'.repeat(p.punches_remaining)}${'<span class="punch used"></span>'.repeat(Math.max(0, used))}</div>`
        : `<div class="meter" role="img" aria-label="${p.punches_remaining} of ${p.punches_total} punches left"><span data-fill="${Math.round((p.punches_remaining / p.punches_total) * 100)}"></span></div>`;
      balance = `<p class="pass-big">${p.punches_remaining}<small> of ${p.punches_total} left</small></p>${holes}`;
    } else {
      balance = `<p class="pass-big">${p.daily_round_limit ? `${p.daily_round_limit}<small> ${p.daily_round_limit === 1 ? "round" : "rounds"} a day</small>` : "Unlimited<small> golf</small>"}</p>`;
    }
    const dates = p.valid_until ? `${fmtDate(p.valid_from)} – ${fmtDate(p.valid_until)}` : `From ${fmtDate(p.valid_from)} · no expiry`;
    return `<article class="pass ${p.kind === "membership" ? "membership" : ""} ${off ? "is-off" : ""}">
      <div class="pass-top"><span class="pass-kind">${p.kind === "membership" ? "Membership" : "Punch card"}</span><span class="pill plain">${passStateLabel(p.state)}</span></div>
      <h3>${esc(p.name)}</h3>
      ${balance}
      <p class="pass-foot">${esc(coversLabel(p.covers))} · ${esc(dates)}${p.uses ? ` · used ${plural(p.uses, "time")}` : ""}</p>
      ${actions}
    </article>`;
  }

  function historyList(items) {
    if (!items.length) return '<p class="empty">Nothing yet.</p>';
    return `<ul class="history">${items.map((item) => `<li>
      <time datetime="${esc(item.occurred_at)}">${esc(fmtStamp(item.occurred_at))}</time>
      <span>${esc(item.description)}</span>
      ${item.billing_status === "unbilled" ? '<span class="pill warn">Unbilled</span>' : item.billing_status === "covered" ? '<span class="pill good">Covered</span>' : "<span></span>"}
    </li>`).join("")}</ul>`;
  }

  const leadIcon = (name) => `<span class="stat-icon">${icon(name)}</span>`;

  function upcomingList(items) {
    if (!items.length) return '<p class="empty">No upcoming tee times.</p>';
    return `<div class="list">${items.map((item) => {
      const local = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: tz() }).format(new Date(item.tee_time));
      const extras = [clubsLabel(item.clubs), item.pull_cart ? "Pull cart" : "", item.checked_in ? "Checked in" : ""].filter(Boolean);
      return `<button class="list-item" type="button" data-action="go" data-view="tee" data-arg="${local}">
        ${leadIcon("tee")}<span><strong>${esc(fmtWhen(item.tee_time))}</strong>
        <small>${plural(item.players, "player")}${extras.length ? ` · ${esc(extras.join(" · "))}` : ""}</small></span>
      </button>`;
    }).join("")}</div>`;
  }

  function rentalList(items) {
    if (!items.length) return "";
    return `<section class="card"><h2>Rentals</h2><div class="list">${items.map((r) => `<div class="list-item plain">
      ${leadIcon(KIND_ICON[r.kind] || "cart")}<span><strong>${esc(r.label)}</strong><small>${esc(fmtWhen(r.starts_at))} · back by ${esc(fmtClock(r.due_at))}</small></span></div>`).join("")}</div></section>`;
  }

  function renderMine() {
    const { player, passes, upcoming, rentals, history } = state.me;
    main.innerHTML = `
      <div class="page-head">
        <div class="hero">${avatar(player.full_name, { large: true })}<div><p class="eyebrow">My golf</p><h1>${esc(player.full_name)}</h1></div></div>
        <div class="actions">${button("Edit details", "edit-me", {}, "tonal")}</div>
      </div>
      <section class="section"><h2>Passes</h2>${passes.length ? `<div class="passes">${passes.map((p) => passCard(p)).join("")}</div>`
        : '<p class="empty card">No punch cards or memberships yet. The pro shop can add them to your account.</p>'}</section>
      <section class="card"><h2>Upcoming tee times</h2>${upcomingList(upcoming)}</section>
      ${rentalList(rentals)}
      <section class="card"><h2>Details</h2><dl class="kv"><dt>Email</dt><dd>${esc(player.email || "—")}</dd><dt>Phone</dt><dd>${esc(player.phone || "—")}</dd></dl></section>
      <section class="card"><h2>History</h2>${historyList(history)}</section>`;
    applyFills(main);
  }

  function openEditMe() {
    const { player } = state.me;
    openSheet({
      title: "Your details",
      body: `
        <label class="field"><span class="label">Name</span><input type="text" name="full_name" maxlength="120" autocomplete="name" value="${esc(player.full_name)}"></label>
        <label class="field"><span class="label">Phone</span><input type="tel" name="phone" maxlength="40" autocomplete="tel" value="${esc(player.phone || "")}"></label>`,
      submit: "Save",
      onSubmit: async (form) => {
        state.me = await api("/me", { method: "PUT", body: { full_name: form.elements.full_name.value, phone: form.elements.phone.value } });
        state.user.full_name = state.me.player.full_name;
        renderChrome();
        renderMine();
        toast("Details saved");
      },
    });
  }

  // ---------------------------------------------------------------- counter (staff)
  async function loadCounter() {
    const [inventory, products] = await Promise.all([api("/inventory"), state.products ? null : api("/products")]);
    state.inventory = inventory;
    if (products) state.products = products.products;
  }

  const UNIT_STATUS = {
    available: ["Available", "good"], reserved: ["Reserved later", "info"], rented: ["Out", "warn"],
    overdue: ["Overdue", "bad"], out_of_service: ["Out of service", ""], retired: ["Retired", ""],
  };

  function unitLine(unit) {
    if (unit.current) {
      return unit.status === "overdue"
        ? `${unit.current.holder} · due ${fmtClock(unit.current.due_at)}`
        : `${unit.current.holder} · back ~${fmtClock(unit.current.due_at)}`;
    }
    if (unit.next) return `Next: ${fmtWhen(unit.next.starts_at)}`;
    return unit.notes || "";
  }

  function renderCounter() {
    const groups = state.inventory.groups;
    main.innerHTML = `
      <div class="page-head">
        <div><p class="eyebrow">Rentals and range</p><h1>Counter</h1></div>
        <div class="actions">${button("Rent now", "rent", {}, "primary")}${button("Range balls", "range", {}, "tonal")}${button(icon("refresh"), "refresh", { label: "Refresh" }, "icon")}</div>
      </div>
      <p class="hint gap-bottom">Estimated returns are ${esc(roundLength())} after the rental starts. Tap a cart or club set to mark it returned or take it out of service.</p>
      ${groups.map((g) => `<section class="unit-group card">
        <header><h2>${esc(g.name)}</h2>
          <div class="row"><span class="pill good">${g.available} of ${g.total} free</span>${g.out ? `<span class="pill warn">${g.out} out</span>` : ""}${g.overdue ? `<span class="pill bad">${g.overdue} overdue</span>` : ""}${g.out_of_service ? `<span class="pill">${g.out_of_service} out of service</span>` : ""}</div>
        </header>
        <div class="units">${g.units.map((u) => `
          <button class="unit" type="button" data-action="unit" data-id="${u.id}" data-status="${u.status}">
            <strong>${esc(u.label)}</strong>
            <span class="pill ${UNIT_STATUS[u.status][1]}">${UNIT_STATUS[u.status][0]}</span>
            <small>${esc(unitLine(u))}</small>
          </button>`).join("") || '<p class="empty">None configured. Set the count in Setup.</p>'}</div>
      </section>`).join("")}`;
  }

  function findUnit(id) {
    for (const group of state.inventory.groups) {
      const unit = group.units.find((u) => u.id === Number(id));
      if (unit) return { group, unit };
    }
    throw new Error("Refresh and try again.");
  }

  function openUnit(id) {
    const { group, unit } = findUnit(id);
    const [label] = UNIT_STATUS[unit.status];
    openSheet({
      title: unit.label,
      body: `
        <p class="lede">${esc(group.name)} · ${esc(label)}</p>
        ${unit.current ? `<div class="card stack">
          <p><b>${esc(unit.current.holder)}</b></p>
          <p>Out since ${esc(fmtClock(unit.current.starts_at))} · estimated return ${esc(fmtClock(unit.current.due_at))}</p>
          ${button("Mark returned", "return-rental", { id: unit.current.id }, "primary")}
        </div>` : ""}
        ${unit.next ? `<p>Next reservation: <b>${esc(unit.next.holder)}</b>, ${esc(fmtWhen(unit.next.starts_at))}${unit.upcoming > 1 ? ` (+${unit.upcoming - 1} more)` : ""}</p>` : ""}
        <label class="toggle"><input type="checkbox" name="in_service" ${unit.in_service ? "checked" : ""}><span>In service</span></label>
        <p class="hint">Taking it out of service moves its upcoming reservations to another free ${esc(group.name.toLowerCase().replace(/s$/, ""))}.</p>
        <label class="field"><span class="label">Notes</span><input type="text" name="notes" maxlength="500" value="${esc(unit.notes)}" placeholder="e.g. Flat tyre on the left wheel"></label>`,
      submit: "Save",
      onSubmit: async (form) => {
        await api(`/rental-units/${id}`, { method: "PUT", body: { in_service: form.elements.in_service.checked, notes: form.elements.notes.value } });
        toast(`${unit.label} saved`);
        await reload();
      },
    });
  }

  function openRent(prefill = null) {
    const kinds = [["riding_cart", "", "Riding cart"], ["pull_cart", "", "Pull cart"], ["club_set", "right", "RH clubs"], ["club_set", "left", "LH clubs"]];
    openSheet({
      title: "Rent now",
      context: { player: prefill },
      body: `
        <div class="field"><span class="label" id="rent-kind">What</span>
          <div class="seg" role="radiogroup" aria-labelledby="rent-kind">${kinds.map(([kind, hand, label], i) =>
            `<label><input type="radio" name="kind" value="${kind}:${hand}" ${i === 0 ? "checked" : ""}><span>${label}</span></label>`).join("")}</div>
        </div>
        ${prefill ? `<p>For <b>${esc(prefill.name)}</b></p>` : `${pickerField("renter", "Player (optional)")}
        <p class="hint" id="renter-note">No player chosen: recorded as a walk-in.</p>
        <label class="field"><span class="label">Walk-in name (optional)</span><input type="text" name="name" maxlength="80" autocomplete="off"></label>`}
        <p class="hint">Starts now; estimated return in ${esc(roundLength())}.</p>`,
      submit: "Rent now",
      onSubmit: async (form) => {
        const [kind, hand] = form.elements.kind.value.split(":");
        const body = { kind };
        if (hand) body.hand = hand;
        if (sheetState.player) body.player_id = sheetState.player.id;
        else if (form.elements.name?.value.trim()) body.name = form.elements.name.value.trim();
        const rental = await api("/rentals", { method: "POST", body });
        toast(`${rental.label} is out`);
        if (state.view === "counter" || state.view === "players") await reload();
      },
    });
    sheetState.onPick = {
      renter: ({ id, name }) => {
        sheetState.player = { id, name };
        $("#renter-note", sheetForm).textContent = `For ${name}.`;
      },
    };
  }

  async function openRange(prefill = null) {
    if (!state.products) state.products = (await api("/products")).products;
    const buckets = state.products.filter((p) => p.kind === "range_bucket" && p.active);
    if (!buckets.length) throw new Error("No range buckets are on offer. Add or turn one on in Setup.");
    const passChoices = (passes) => `
      ${passes.map((p) => `<label class="choice"><input type="radio" name="pay" value="${p.id}"><span><b>Use ${esc(p.name)}</b><small>${esc(passDetail(p))}</small></span></label>`).join("")}
      <label class="choice"><input type="radio" name="pay" value="" checked><span><b>Record as unbilled</b><small>Settled at the counter</small></span></label>`;
    const rangePasses = async (id) => (await api(`/players/${id}`)).passes.filter((p) => p.state === "active" && p.covers !== "round");
    openSheet({
      title: "Range balls",
      context: { player: prefill },
      body: `
        <div class="field"><span class="label">Bucket</span><div class="choices">${buckets.map((b, i) => `
          <label class="choice"><input type="radio" name="bucket" value="${b.id}" ${i === 0 ? "checked" : ""}><span><b>${esc(b.name)}</b><small>${b.balls} balls · ${esc(money(b.price_cents))}</small></span></label>`).join("")}</div></div>
        <div class="field"><span class="label" id="qty-label">How many buckets</span>${choiceSeg("quantity", countOptions(4), 1, "qty-label")}</div>
        ${prefill ? `<p>For <b>${esc(prefill.name)}</b></p>` : `${pickerField("buyer", "Player (optional)")}<p class="hint" id="buyer-note">No player chosen: recorded as a walk-in sale.</p>`}
        <div class="field"><span class="label">Payment</span><div class="choices" id="pay">${passChoices(prefill ? await rangePasses(prefill.id) : [])}</div></div>`,
      submit: "Record",
      onSubmit: async (form) => {
        const body = { product_id: Number(form.elements.bucket.value), quantity: Number(form.elements.quantity.value) || 1 };
        if (sheetState.player) body.player_id = sheetState.player.id;
        if (form.elements.pay.value) body.pass_id = Number(form.elements.pay.value);
        await api("/range-buckets", { method: "POST", body });
        toast("Range balls recorded");
        if (state.view === "players" || state.view === "mine") await reload();
      },
    });
    sheetState.onPick = {
      buyer: async ({ id, name }) => {
        sheetState.player = { id, name };
        $("#buyer-note", sheetForm).textContent = `For ${name}.`;
        $("#pay", sheetForm).innerHTML = passChoices(await rangePasses(id));
      },
    };
  }

  // ---------------------------------------------------------------- players (staff)
  async function loadPlayers(id) {
    const [list, detail, products] = await Promise.all([
      api(`/players?q=${encodeURIComponent(state.playerQuery)}`),
      id ? api(`/players/${encodeURIComponent(id)}`) : null,
      state.products ? null : api("/products"),
    ]);
    state.players = list.players;
    state.player = detail;
    if (products) state.products = products.products;
  }

  function playerListItems() {
    if (!state.players.length) return `<p class="empty">${state.playerQuery ? "No players match." : "No players yet."}</p>`;
    return state.players.map((p) => `
      <button class="list-item" type="button" data-action="go" data-view="players" data-arg="${p.id}" ${state.player?.player.id === p.id ? 'aria-current="true"' : ""}>
        ${avatar(p.full_name)}<span><strong>${esc(p.full_name)}</strong>
        <small>${esc([p.email, p.phone].filter(Boolean).join(" · ") || "No contact details")}</small>
        <small>${p.has_account ? "App account" : "No app account"}${p.active_passes ? ` · ${plural(p.active_passes, "active pass", "active passes")}` : ""}</small></span>
      </button>`).join("");
  }

  function renderPlayers() {
    const detail = state.player;
    main.innerHTML = `
      <div class="split ${detail ? "has-detail" : ""}">
        <section class="split-list card">
          <div class="page-head"><h1>Players</h1>${button("New player", "new-player", {}, "primary")}</div>
          <label class="field"><span class="sr-only">Search players</span>
            <input type="search" id="player-search" placeholder="Search by name, email or phone" value="${esc(state.playerQuery)}" autocomplete="off" enterkeyhint="search">
          </label>
          <div class="list gap-top" id="player-list">${playerListItems()}</div>
        </section>
        <section class="split-detail">${detail ? playerDetail(detail) : '<div class="card empty">Choose a player to see their passes, tee times and history.</div>'}</section>
      </div>`;
    applyFills(main);
    let timer = 0;
    $("#player-search").addEventListener("input", (event) => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        state.playerQuery = event.target.value.trim();
        try {
          state.players = (await api(`/players?q=${encodeURIComponent(state.playerQuery)}`)).players;
          $("#player-list").innerHTML = playerListItems();
        } catch (error) {
          showError(error);
        }
      }, 250);
    });
  }

  function playerDetail(profile) {
    const p = profile.player;
    const code = p.claim_code_expires_at && new Date(p.claim_code_expires_at) > new Date()
      ? `<p class="hint">A sign-up code is waiting to be used (expires ${esc(fmtStamp(p.claim_code_expires_at))}).</p>` : "";
    return `
      ${button(`${icon("back")}All players`, "go", { view: "players" }, "quiet back-link")}
      <div class="page-head">
        <div class="hero">${avatar(p.full_name, { large: true })}<div><p class="eyebrow">${p.has_account ? "App account" : "Player record"}</p><h1>${esc(p.full_name)}</h1></div></div>
        <div class="actions">${button("Edit", "edit-player", {}, "tonal")}${p.has_account ? "" : button("Sign-up code", "player-code", {}, "tonal")}</div>
      </div>
      <section class="card">
        <dl class="kv">
          <dt>Email</dt><dd>${esc(p.email || "—")}</dd>
          <dt>Phone</dt><dd>${esc(p.phone || "—")}</dd>
          <dt>App</dt><dd>${p.has_account ? `Signed up as ${esc(p.account_email)}${p.role === "staff" ? " (staff)" : ""}` : "No app account"}</dd>
          ${p.notes ? `<dt>Notes</dt><dd>${esc(p.notes)}</dd>` : ""}
        </dl>
        ${code}
        <div class="row gap-top">${button("Issue pass", "issue-pass", {}, "primary")}${button("Range balls", "range-for", {}, "tonal")}${button("Rent now", "rent-for", {}, "tonal")}</div>
      </section>
      <section class="section"><h2>Passes</h2>${profile.passes.length
        ? `<div class="passes">${profile.passes.map((pass) => passCard(pass, `<div>${button("Adjust", "adjust-pass", { id: pass.id }, "btn-on-pass")}</div>`)).join("")}</div>`
        : '<p class="card empty">No passes yet.</p>'}</section>
      <section class="card"><h2>Upcoming tee times</h2>${upcomingList(profile.upcoming)}</section>
      ${rentalList(profile.rentals)}
      <section class="card"><h2>History</h2>${historyList(profile.history)}</section>`;
  }

  function playerForm(p = {}) {
    return `
      <label class="field"><span class="label">Name</span><input type="text" name="full_name" maxlength="120" autocomplete="off" autocapitalize="words" value="${esc(p.full_name || "")}"></label>
      <label class="field"><span class="label">Email</span><input type="email" name="email" maxlength="254" autocomplete="off" value="${esc(p.email || "")}"></label>
      <label class="field"><span class="label">Phone</span><input type="tel" name="phone" maxlength="40" autocomplete="off" value="${esc(p.phone || "")}"></label>
      <label class="field"><span class="label">Notes (staff only)</span><textarea name="notes" maxlength="2000">${esc(p.notes || "")}</textarea></label>`;
  }

  const playerFields = (form) => ({ full_name: form.elements.full_name.value, email: form.elements.email.value,
    phone: form.elements.phone.value, notes: form.elements.notes.value });

  function openNewPlayer() {
    openSheet({
      title: "New player", body: playerForm(), submit: "Add player",
      onSubmit: async (form) => {
        const { player_id: id } = await api("/players", { method: "POST", body: playerFields(form) });
        toast("Player added");
        go("players", String(id));
      },
    });
  }

  function openEditPlayer() {
    const p = state.player.player;
    openSheet({
      title: `Edit ${p.full_name}`, body: playerForm(p), submit: "Save",
      onSubmit: async (form) => {
        state.player = await api(`/players/${p.id}`, { method: "PUT", body: playerFields(form) });
        toast("Saved");
        await reload();
      },
    });
  }

  function openIssuePass() {
    const p = state.player.player;
    const products = (state.products || []).filter((x) => (x.kind === "punch_card" || x.kind === "membership") && x.active);
    if (!products.length) throw new Error("No punch cards or memberships are on offer. Add one in Setup.");
    openSheet({
      title: `Issue a pass to ${p.full_name}`,
      body: `
        <div class="choices">${products.map((x, i) => `<label class="choice"><input type="radio" name="product" value="${x.id}" ${i === 0 ? "checked" : ""}>
          <span><b>${esc(x.name)}</b><small>${esc(productDetail(x))} · ${esc(money(x.price_cents))}</small></span></label>`).join("")}</div>
        <label class="field"><span class="label">Starts</span><input type="date" name="valid_from" value="${esc(state.today)}"></label>
        <p class="hint">The pass is recorded as unbilled; no payment is taken in the app.</p>`,
      submit: "Issue pass",
      onSubmit: async (form) => {
        await api(`/players/${p.id}/passes`, { method: "POST", body: { product_id: Number(form.elements.product.value), valid_from: form.elements.valid_from.value } });
        toast("Pass issued");
        await reload();
      },
    });
  }

  function openAdjustPass(id) {
    const pass = state.player.passes.find((x) => x.id === Number(id));
    openSheet({
      title: `Adjust ${pass.name}`,
      body: `
        <p class="muted">${esc(passDetail(pass))}</p>
        ${pass.kind === "punch_card" ? `<div class="field"><span class="label">Add or remove punches</span>${stepper("delta", 0, -pass.punches_remaining, 500, "Punch change")}</div>` : ""}
        <label class="field"><span class="label">Valid through${pass.kind === "punch_card" ? " (leave empty for no expiry)" : ""}</span>
          <input type="date" name="valid_until" value="${esc(pass.valid_until || "")}" min="${esc(pass.valid_from)}"></label>
        <div class="field"><span class="label" id="pass-status">Status</span><div class="seg" role="radiogroup" aria-labelledby="pass-status">
          <label><input type="radio" name="status" value="active" ${pass.status === "active" ? "checked" : ""}><span>Active</span></label>
          <label><input type="radio" name="status" value="void" ${pass.status === "void" ? "checked" : ""}><span>Void</span></label>
        </div></div>
        <label class="field"><span class="label">Reason (kept in the player's history)</span><input type="text" name="reason" maxlength="200" placeholder="e.g. Rain check, 12 Nov"></label>`,
      submit: "Save changes",
      onSubmit: async (form) => {
        const body = { reason: form.elements.reason.value };
        const delta = Number(form.elements.delta?.value || 0);
        if (delta) body.punches_delta = delta;
        if ((form.elements.valid_until.value || null) !== (pass.valid_until || null)) body.valid_until = form.elements.valid_until.value || null;
        if (form.elements.status.value !== pass.status) body.status = form.elements.status.value;
        await api(`/passes/${id}/adjust`, { method: "POST", body });
        toast("Pass updated");
        await reload();
      },
    });
  }

  async function openPlayerCode() {
    const p = state.player.player;
    const { code, expires_at: expires } = await api(`/players/${p.id}/player-code`, { method: "POST", body: {} });
    openSheet({
      title: "Sign-up code",
      body: `
        <p>Give ${esc(p.full_name)} this code. When they create an account in the app, it links to this player record with their passes and history.</p>
        <p class="big-code">${esc(code)}</p>
        <p class="hint">Works once, until ${esc(fmtStamp(expires))}. Making a new code cancels this one.</p>`,
      submit: "Done", cancel: "",
    });
    await reload();
  }

  // ---------------------------------------------------------------- setup (staff)
  async function loadSetup() {
    const [settings, products] = await Promise.all([api("/settings"), api("/products")]);
    state.settings = settings.settings;
    state.products = products.products;
  }

  const KIND_LABEL = { green_fee: "Green fee", punch_card: "Punch card", membership: "Membership", range_bucket: "Range bucket",
    riding_cart_rental: "Riding cart rental", pull_cart_rental: "Pull cart rental", club_rental: "Club rental" };

  function productDetail(x) {
    if (x.kind === "punch_card") return `${x.punches} ${x.covers === "range" ? "range buckets" : "rounds"}${x.valid_days ? ` · valid ${x.valid_days} days` : " · no expiry"}`;
    if (x.kind === "membership") return `${x.daily_round_limit ? `${plural(x.daily_round_limit, "round")} a day` : "Unlimited golf"}${x.includes_range ? " + range balls" : ""} · ${x.valid_days} days`;
    if (x.kind === "range_bucket") return `${x.bucket_size === "large" ? "Large" : "Small"} · ${x.balls} balls`;
    return KIND_LABEL[x.kind];
  }

  function numberField(name, label, value, min, max) {
    return `<label class="field"><span class="label">${label}</span><input type="number" name="${name}" inputmode="numeric" min="${min}" max="${max}" value="${esc(value)}"></label>`;
  }

  function setRow(label, control, note = "") {
    return `<label class="set-row"><span><span class="label">${label}</span>${note ? `<small>${esc(note)}</small>` : ""}</span>${control}</label>`;
  }

  const numberInput = (name, value, min, max) =>
    `<input type="number" name="${name}" inputmode="numeric" min="${min}" max="${max}" value="${esc(value)}">`;

  function renderSetup() {
    const s = state.settings;
    main.innerHTML = `
      <div class="page-head"><div><p class="eyebrow">Course staff</p><h1>Setup</h1></div></div>
      <form id="settings-form" novalidate>
        <h2 class="group-title">Course</h2>
        <div class="group">
          ${setRow("Course name", `<input type="text" name="course_name" maxlength="80" value="${esc(s.course_name)}">`)}
          ${setRow("Time zone", `<input type="text" name="time_zone" value="${esc(s.time_zone)}" list="zones" autocomplete="off">`)}
          ${setRow("First tee time", `<input type="time" name="opening_time" value="${esc(s.opening_time)}">`)}
          ${setRow("Last tee time", `<input type="time" name="closing_time" value="${esc(s.closing_time)}">`)}
          ${setRow("Minutes between tee times", numberInput("tee_interval_minutes", s.tee_interval_minutes, 5, 60))}
          ${setRow("Average round (minutes)", numberInput("average_round_minutes", s.average_round_minutes, 30, 720), "Sets estimated returns for carts and clubs")}
          ${setRow("Booking window (days)", numberInput("booking_window_days", s.booking_window_days, 1, 365), "How far ahead players can book")}
        </div>
        <datalist id="zones">${["America/Los_Angeles", "America/Denver", "America/Phoenix", "America/Chicago", "America/New_York", "America/Anchorage", "Pacific/Honolulu"].map((z) => `<option value="${z}">`).join("")}</datalist>
        <h2 class="group-title gap-top">Rental inventory</h2>
        <div class="group">
          ${setRow("Riding carts", numberInput("riding_cart_count", s.riding_cart_count, 0, 200))}
          ${setRow("Pull carts", numberInput("pull_cart_count", s.pull_cart_count, 0, 200))}
          ${setRow("Right-handed club sets", numberInput("club_sets_right", s.club_sets_right, 0, 200))}
          ${setRow("Left-handed club sets", numberInput("club_sets_left", s.club_sets_left, 0, 200))}
        </div>
        <p class="form-error" role="alert" id="settings-error"></p>
        <div class="row gap-top"><button class="btn btn-primary" type="submit">Save settings</button></div>
      </form>
      <div class="page-head gap-top"><div><h2>Catalog</h2><p class="hint">Prices are kept for bookkeeping only. The app does not take payments.</p></div>${button(`${icon("plus")}Add product`, "new-product", {}, "tonal")}</div>
      <div class="group">${state.products.map((x) => `
          <button class="list-item" type="button" data-action="edit-product" data-id="${x.id}">
            ${leadIcon({ punch_card: "tee", membership: "seat", range_bucket: "clock", riding_cart_rental: "cart", pull_cart_rental: "pull", club_rental: "clubs" }[x.kind] || "calendar")}
            <span><strong>${esc(x.name)} ${x.active ? "" : '<span class="pill plain">Off</span>'}</strong>
            <small>${esc(KIND_LABEL[x.kind])} · ${esc(productDetail(x))} · ${esc(money(x.price_cents))}</small></span>
          </button>`).join("")}</div>`;
    $("#settings-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const body = {};
      for (const field of ["course_name", "time_zone", "opening_time", "closing_time"]) body[field] = form.elements[field].value;
      for (const field of ["tee_interval_minutes", "average_round_minutes", "booking_window_days", "riding_cart_count", "pull_cart_count", "club_sets_right", "club_sets_left"]) {
        body[field] = Number(form.elements[field].value);
      }
      const error = $("#settings-error");
      error.textContent = "";
      try {
        state.settings = (await api("/settings", { method: "PUT", body })).settings;
        state.course = { ...state.course, ...state.settings };
        renderChrome();
        toast("Settings saved");
      } catch (err) {
        error.textContent = err.message;
      }
    });
  }

  function openProduct(id = null) {
    const product = id ? state.products.find((x) => x.id === Number(id)) : null;
    const kind = product?.kind || "punch_card";
    const priceValue = product?.price_cents == null ? "" : (product.price_cents / 100).toFixed(2);
    const kindPicker = product ? `<p class="lede">${esc(KIND_LABEL[kind])}</p>` : `
      <div class="field"><span class="label" id="new-kind">Kind</span><div class="seg" role="radiogroup" aria-labelledby="new-kind">
        ${["punch_card", "membership", "range_bucket"].map((k, i) => `<label><input type="radio" name="kind" value="${k}" ${i === 0 ? "checked" : ""} data-action="product-kind"><span>${KIND_LABEL[k]}</span></label>`).join("")}
      </div></div>`;
    openSheet({
      title: product ? `Edit ${product.name}` : "Add product",
      body: `${kindPicker}
        <label class="field"><span class="label">Name</span><input type="text" name="name" maxlength="80" value="${esc(product?.name || "")}"></label>
        <label class="field"><span class="label">Price (bookkeeping only)</span><input type="text" name="price" inputmode="decimal" placeholder="e.g. 45.00" value="${esc(priceValue)}"></label>
        <label class="toggle"><input type="checkbox" name="active" ${!product || product.active ? "checked" : ""}><span>On offer</span></label>
        <div id="kind-fields" class="stack">${kindFields(kind, product)}</div>`,
      submit: product ? "Save" : "Add product",
      onSubmit: async (form) => {
        const chosenKind = product?.kind || form.elements.kind.value;
        const price = form.elements.price.value.trim();
        if (price && !/^\d+(\.\d{1,2})?$/.test(price)) throw new Error("Enter the price like 45 or 45.00");
        const body = { name: form.elements.name.value, active: form.elements.active.checked,
          price_cents: price ? Math.round(Number(price) * 100) : null };
        const num = (name) => (form.elements[name]?.value === "" ? null : Number(form.elements[name]?.value));
        if (chosenKind === "punch_card") Object.assign(body, { punches: num("punches"), valid_days: num("valid_days"), covers: form.elements.covers.value });
        if (chosenKind === "membership") Object.assign(body, { valid_days: num("valid_days"), daily_round_limit: num("daily_round_limit"), includes_range: form.elements.includes_range.checked });
        if (chosenKind === "range_bucket") Object.assign(body, { bucket_size: form.elements.bucket_size.value, balls: num("balls") });
        if (product) await api(`/products/${product.id}`, { method: "PUT", body });
        else await api("/products", { method: "POST", body: { ...body, kind: chosenKind } });
        state.products = null;
        toast("Catalog saved");
        await reload();
      },
    });
  }

  function kindFields(kind, x = null) {
    if (kind === "punch_card") return `
      ${numberField("punches", "Punches", x?.punches ?? 10, 1, 500)}
      <div class="field"><span class="label" id="covers-label">Each punch covers</span><div class="seg" role="radiogroup" aria-labelledby="covers-label">
        <label><input type="radio" name="covers" value="round" ${x?.covers !== "range" ? "checked" : ""}><span>A round</span></label>
        <label><input type="radio" name="covers" value="range" ${x?.covers === "range" ? "checked" : ""}><span>A range bucket</span></label>
      </div></div>
      <label class="field"><span class="label">Valid for (days, empty for no expiry)</span><input type="number" name="valid_days" inputmode="numeric" min="1" max="3660" value="${esc(x ? x.valid_days ?? "" : 365)}"></label>`;
    if (kind === "membership") return `
      ${numberField("valid_days", "Valid for (days)", x?.valid_days ?? 365, 1, 3660)}
      <label class="field"><span class="label">Rounds per day (empty for unlimited)</span><input type="number" name="daily_round_limit" inputmode="numeric" min="1" max="10" value="${esc(x?.daily_round_limit ?? "")}"></label>
      <label class="toggle"><input type="checkbox" name="includes_range" ${x?.includes_range ? "checked" : ""}><span>Includes range balls</span></label>`;
    if (kind === "range_bucket") return `
      <div class="field"><span class="label" id="size-label">Size</span><div class="seg" role="radiogroup" aria-labelledby="size-label">
        <label><input type="radio" name="bucket_size" value="small" ${x?.bucket_size !== "large" ? "checked" : ""}><span>Small</span></label>
        <label><input type="radio" name="bucket_size" value="large" ${x?.bucket_size === "large" ? "checked" : ""}><span>Large</span></label>
      </div></div>
      ${numberField("balls", "Balls", x?.balls ?? 40, 1, 1000)}`;
    return '<p class="hint">Used for bookkeeping on check-ins and rentals.</p>';
  }

  // ---------------------------------------------------------------- account
  function openAccount(mode = "signin") {
    if (state.user) {
      openSheet({
        title: "Account",
        body: `<p><b>${esc(state.user.full_name)}</b></p><p class="muted">${esc(state.user.email)}${isStaff() ? " · Course staff" : ""}</p>`,
        submit: "Sign out", danger: true, cancel: "Close",
        onSubmit: async () => {
          await api("/auth/logout", { method: "POST", body: {} });
          state.user = null;
          state.products = null;
          toast("Signed out");
          go("tee");
        },
      });
      return;
    }
    const register = mode === "register";
    openSheet({
      title: register ? "Create an account" : "Sign in",
      body: `
        ${register ? `<label class="field"><span class="label">Your name</span><input type="text" name="full_name" maxlength="120" autocomplete="name" autocapitalize="words"></label>` : ""}
        <label class="field"><span class="label">Email</span><input type="email" name="email" autocomplete="email" autocapitalize="off" spellcheck="false"></label>
        <label class="field"><span class="label">Password${register ? " (at least 10 characters)" : ""}</span><input type="password" name="password" autocomplete="${register ? "new-password" : "current-password"}"></label>
        ${register ? `<label class="field"><span class="label">Phone (optional)</span><input type="tel" name="phone" autocomplete="tel"></label>
        <label class="field"><span class="label">Player code from the pro shop (optional)</span><input type="text" name="player_code" autocomplete="off" autocapitalize="characters" placeholder="ABCD-EFGH"></label>
        <p class="hint">Have a punch card or membership already? Ask the pro shop for a player code so they show up in your account.</p>` : ""}
        ${button(register ? "I already have an account" : "Create an account", "account-mode", { mode: register ? "signin" : "register" }, "quiet")}`,
      submit: register ? "Create account" : "Sign in",
      onSubmit: async (form) => {
        const body = { email: form.elements.email.value, password: form.elements.password.value };
        if (register) Object.assign(body, { full_name: form.elements.full_name.value, phone: form.elements.phone.value, player_code: form.elements.player_code.value });
        const { user } = await api(`/auth/${register ? "register" : "login"}`, { method: "POST", body });
        state.user = user;
        toast(register ? "Welcome! You're signed in." : `Welcome back, ${user.full_name.split(" ")[0]}`);
        renderChrome();
        await route();
      },
    });
  }

  // ---------------------------------------------------------------- actions
  const ACTIONS = {
    go: (d) => go(d.view, d.arg || null),
    theme: () => openTheme(),
    "set-theme": (_, el) => applyTheme(el.value),
    retry: () => (state.course ? route() : boot()),
    refresh: async () => { await reload(); toast("Up to date"); },
    account: () => openAccount(),
    "account-mode": (d) => openAccount(d.mode),
    day: (d) => setDate(addDays(state.sheet.date, Number(d.delta))),
    "set-day": (d) => setDate(d.date),
    "pick-date": () => {
      const input = $("#date-input");
      if (typeof input.showPicker === "function") {
        try { input.showPicker(); return; } catch { /* fall through to focus */ }
      }
      input.focus();
      input.click();
    },
    today: () => setDate(state.today),
    book: (d) => openBook(d.time),
    join: (d) => openJoin(d.booking, false),
    "add-players": (d) => openJoin(d.booking, true),
    carts: (d) => openCarts(d.booking),
    player: (d) => openPlayer(d.booking, d.player),
    leave: (d) => {
      const { slot, booking } = findBooking(d.booking);
      const when = `${esc(fmtSlot(slot.time))} tee time`;
      const party = myParty(booking).map((p) => (p.is_me ? "you" : p.name));
      const others = booking.players.filter((p) => !myParty(booking).includes(p)).map((p) => p.name);
      if (cancelsWholeTeeTime(booking)) {
        confirmSheet("Cancel this tee time?", `${esc(nameList(party.map((n) => (n === "you" ? "You" : n))))} will be removed from the ${when}, the time opens up for others, and the rental clubs and carts are released.`,
          "Cancel tee time", async () => {
            await api(`/bookings/${d.booking}/leave`, { method: "POST", body: {} });
            toast(`The ${fmtSlot(slot.time)} tee time is cancelled`);
            await reload();
          });
        return;
      }
      const guests = party.filter((n) => n !== "you");
      confirmSheet("Cancel your booking?", `${guests.length ? `You and your guests (${esc(nameList(guests))}) are` : "You are"} removed from the ${when} and your rental clubs and carts released. ${esc(nameList(others))} joined on their own and keep${others.length === 1 ? "s" : ""} ${others.length === 1 ? "their spot" : "their spots"}.`,
        "Cancel my booking", async () => {
          await api(`/bookings/${d.booking}/leave`, { method: "POST", body: {} });
          toast("Your booking is cancelled");
          await reload();
        });
    },
    "cancel-booking": (d) => {
      const { slot } = findBooking(d.booking);
      confirmSheet("Cancel this tee time?", `The whole ${esc(fmtSlot(slot.time))} group is removed and its rental reservations released. Players see it in their history.`, "Cancel tee time", async () => {
        await api(`/bookings/${d.booking}`, { method: "DELETE" });
        toast("Tee time cancelled");
        await reload();
      });
    },
    "remove-player": (d) => {
      const { player } = findPlayer(d.booking, d.player);
      confirmSheet(`Remove ${player.name}?`, "Their rental reservations are released too.", "Remove", async () => {
        await api(`/booking-players/${d.player}`, { method: "DELETE" });
        toast(`${player.name} removed`);
        await reload();
      });
    },
    "check-in": (d) => openCheckIn(d.booking, d.player),
    "undo-check-in": async (d) => {
      await api(`/booking-players/${d.player}/check-in`, { method: "DELETE" });
      closeSheet();
      toast("Check-in undone");
      await reload();
    },
    "open-player": (d) => { closeSheet(); go("players", d.id); },
    // Tapping a tee time: an open one goes straight to booking, a booked one to edit or cancel.
    slot: (d) => {
      const slot = state.sheet?.slots.find((s) => s.time === d.time);
      if (slot && !slot.booking && slot.bookable) return openBook(d.time);
      if (slot && !slot.booking && !slot.past && !state.user) return openAccount();
      return openSlot(d.time);
    },
    "party-size": (_, el) => setPartySize(Number(el.value)),
    "add-known": () => {
      const party = $("#party", sheetForm);
      if (!$("[data-picker=add]", sheetForm)) {
        party.insertAdjacentHTML("afterend", pickerField("add", "Find a player to add"));
        sheetState.onPick = { ...(sheetState.onPick || {}), add: ({ id, name }) => {
          if ($(`.party-row[data-player-id="${id}"]`, sheetForm)) throw new Error(`${name} is already in this list.`);
          addPartyRow({ kind: "player", name, playerId: id });
          $("[data-picker=add]", sheetForm).remove();
        } };
      }
      $("[data-picker-input=add]", sheetForm).focus();
    },
    "remove-row": (_, el) => {
      el.closest(".party-row").remove();
      syncPartyLimits();
    },
    step: (d, el) => {
      const input = $("input", el.closest("[data-stepper]"));
      input.value = clamp((Number(input.value) || 0) + Number(d.step), Number(input.min), Number(input.max));
    },
    pick: async (d) => {
      const handler = sheetState.onPick?.[d.picker];
      $(`#picker-${d.picker}`, sheetForm).innerHTML = "";
      const input = $(`[data-picker-input="${d.picker}"]`, sheetForm);
      if (input) input.value = d.name;
      if (handler) await handler({ id: Number(d.id), name: d.name });
    },
    unit: (d) => openUnit(d.id),
    "return-rental": async (d) => {
      await api(`/rentals/${d.id}/return`, { method: "POST", body: {} });
      closeSheet();
      toast("Marked returned");
      await reload();
    },
    rent: () => openRent(),
    range: () => openRange(),
    "rent-for": () => openRent({ id: state.player.player.id, name: state.player.player.full_name }),
    "range-for": () => openRange({ id: state.player.player.id, name: state.player.player.full_name }),
    "new-player": () => openNewPlayer(),
    "edit-player": () => openEditPlayer(),
    "issue-pass": () => openIssuePass(),
    "adjust-pass": (d) => openAdjustPass(d.id),
    "player-code": () => openPlayerCode(),
    "edit-me": () => openEditMe(),
    "new-product": () => openProduct(),
    "edit-product": (d) => openProduct(d.id),
    "product-kind": (_, el) => { $("#kind-fields", sheetForm).innerHTML = kindFields(el.value); },
  };

  function addPartyRow(row) {
    const party = $("#party", sheetForm);
    const max = sheetState.maxRows ?? 4;
    if ($$(".party-row", party).length >= max) throw new Error(`This group has room for ${plural(max, "player")}.`);
    party.insertAdjacentHTML("beforeend", partyRow(row));
    syncPartyLimits();
    const input = $(".party-row:last-child input[type=text]", party);
    if (input && matchMedia("(pointer: fine)").matches) input.focus();
  }

  // The 1 2 3 4 choice: add empty guest rows or drop the last ones to match.
  function setPartySize(size) {
    const party = $("#party", sheetForm);
    let rows = $$(".party-row", party);
    while (rows.length < size) {
      party.insertAdjacentHTML("beforeend", partyRow({ kind: "guest" }));
      rows = $$(".party-row", party);
    }
    for (const row of rows.slice(size).reverse()) {
      if (row.dataset.kind !== "me") row.remove();
    }
    syncPartyLimits();
  }

  function syncPartyLimits() {
    const count = $$(".party-row", sheetForm).length;
    const size = $$('input[name="party-size"]', sheetForm).find((input) => Number(input.value) === count);
    if (size) size.checked = true;
    const riding = $("#riding-seg", sheetForm);
    if (riding) {
      const current = Math.min(Number(sheetForm.elements.riding?.value || 0), count);
      riding.outerHTML = choiceSeg("riding", ridingOptions(Math.max(count, 1)), current, "riding-label");
    }
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) {
      event.preventDefault();
      closeSheet();
      return;
    }
    const el = event.target.closest("[data-action]");
    if (!el || el.disabled) return;
    const handler = ACTIONS[el.dataset.action];
    if (!handler) return;
    if (el.tagName !== "INPUT") event.preventDefault();
    Promise.resolve().then(() => handler(el.dataset, el)).catch(showError);
  });

  // ---------------------------------------------------------------- drag to scroll with a mouse
  // On touchscreen PCs people use the mouse like a finger: press anywhere and drag to scroll the tee
  // sheet, the day strip or a sheet, with a little momentum when let go. A press that moves less than
  // a few pixels is still an ordinary click.
  (function dragToScroll() {
    const THRESHOLD = 6;
    let drag = null;
    let glide = 0;
    let swallowClick = false;

    const scrollerFor = (target) => {
      const strip = target.closest(".days, .stats");
      if (strip) return { el: strip, axis: "x" };
      const body = target.closest(".sheet-body");
      if (body) return { el: body, axis: "y" };
      if (target.closest("dialog")) return null;
      return { el: document.scrollingElement || document.documentElement, axis: "y" };
    };

    document.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      if (event.target.closest("input:not([type=radio]):not([type=checkbox]), textarea, select, [contenteditable], .no-drag")) return;
      const scroller = scrollerFor(event.target);
      if (!scroller) return;
      cancelAnimationFrame(glide);
      drag = { ...scroller, x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY,
        lastT: event.timeStamp, velocity: 0, moved: false };
    });

    document.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerType !== "mouse") return;
      if (!(event.buttons & 1)) { drag = null; return; }
      const delta = drag.axis === "x" ? event.clientX - drag.lastX : event.clientY - drag.lastY;
      if (!drag.moved) {
        const total = drag.axis === "x" ? event.clientX - drag.x : event.clientY - drag.y;
        if (Math.abs(total) < THRESHOLD) return;
        drag.moved = true;
        document.documentElement.classList.add("is-dragging");
        getSelection()?.removeAllRanges();
      }
      if (drag.axis === "x") drag.el.scrollLeft -= delta;
      else drag.el.scrollTop -= delta;
      const dt = Math.max(1, event.timeStamp - drag.lastT);
      drag.velocity = 0.8 * (delta / dt) + 0.2 * drag.velocity;
      drag.lastX = event.clientX;
      drag.lastY = event.clientY;
      drag.lastT = event.timeStamp;
    });

    const finish = (event) => {
      if (!drag) return;
      const { el, axis, moved } = drag;
      let velocity = drag.velocity;
      drag = null;
      if (!moved) return;
      document.documentElement.classList.remove("is-dragging");
      swallowClick = event.type === "pointerup";
      if (swallowClick) setTimeout(() => { swallowClick = false; }, 60);
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      let last = performance.now();
      const step = (now) => {
        const dt = now - last;
        last = now;
        velocity *= Math.pow(0.95, dt / 16);
        if (Math.abs(velocity) < 0.02) return;
        if (axis === "x") el.scrollLeft -= velocity * dt;
        else el.scrollTop -= velocity * dt;
        glide = requestAnimationFrame(step);
      };
      glide = requestAnimationFrame(step);
    };
    document.addEventListener("pointerup", finish);
    document.addEventListener("pointercancel", finish);

    // Capture phase: a drag must not also press the button, chip or switch it started on.
    window.addEventListener("click", (event) => {
      if (!swallowClick) return;
      swallowClick = false;
      event.preventDefault();
      event.stopPropagation();
    }, true);
    // A real wheel or touch scroll stops any glide in progress.
    window.addEventListener("wheel", () => cancelAnimationFrame(glide), { passive: true });
    document.addEventListener("dragstart", (event) => event.preventDefault());
  })();

  // ---------------------------------------------------------------- start
  async function boot() {
    renderThemeButton();
    try {
      const info = await api("/app");
      state.course = info.course;
      state.today = info.today;
      state.user = info.user;
    } catch (error) {
      main.innerHTML = `<div class="error-panel"><p>${esc(error.message)}</p>${button("Try again", "retry", {}, "primary")}</div>`;
      return;
    }
    renderChrome();
    await route();
  }

  window.addEventListener("hashchange", route);
  window.addEventListener("online", () => setOffline(false));
  window.addEventListener("offline", () => setOffline(true));

  // Keep the counter and tee sheet current on shared screens without interrupting anyone mid-task.
  setInterval(() => {
    if (document.visibilityState !== "visible" || dialog.open || !state.course) return;
    if (state.view === "tee" || state.view === "counter") reload().catch(() => {});
  }, 60_000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.course && !dialog.open) reload().catch(() => {});
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/golf/sw.js", { scope: "/golf/" }).catch(() => {});
  }

  boot();
})();
