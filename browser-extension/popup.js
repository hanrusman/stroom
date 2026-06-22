"use strict";

// Base van de Stroom-API. De nginx-frontend proxyt /api/* door naar stroom-api.
const BASE = "https://stroom.c4w.nl";

const $ = (id) => document.getElementById(id);

/** Wrapper rond fetch die de sessie-cookie meestuurt en nette fouten geeft. */
async function api(path, init = {}) {
  let r;
  try {
    r = await fetch(BASE + path, { credentials: "include", ...init });
  } catch (e) {
    throw new Error("Geen verbinding met stroom.c4w.nl (" + e.message + ")");
  }
  if (r.status === 401) {
    throw new Error(
      "Niet ingelogd op Stroom. Open stroom.c4w.nl, log in, en probeer opnieuw."
    );
  }
  if (r.status === 403) {
    throw new Error(
      "Geweigerd door Stroom (origin). Het extensie-ID moet nog in STROOM_ALLOWED_ORIGINS."
    );
  }
  if (!r.ok) {
    let detail = String(r.status);
    try {
      const j = await r.json();
      if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return r;
}

const getTopics = () => api("/api/inbox/topics").then((r) => r.json());

const fetchMeta = (url) =>
  api("/api/inbox/fetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  }).then((r) => r.json());

const submit = (body) =>
  api("/api/inbox/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());

/** Huidige actieve tab (url + titel). */
function currentTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) =>
      resolve(tabs && tabs[0] ? tabs[0] : null)
    );
  });
}

function setStatus(msg, kind) {
  const el = $("status");
  el.textContent = msg || "";
  el.className = kind || "";
}

/** Toon een fatale fout: een rode regel + optioneel een 'Open Stroom'-link. */
function fatal(message, withLink) {
  $("loading").classList.add("hidden");
  $("form").classList.add("hidden");
  const el = $("fatal");
  el.classList.remove("hidden");
  el.textContent = "";
  const p = document.createElement("p");
  p.style.color = "var(--err)";
  p.textContent = message;
  el.appendChild(p);
  if (withLink) {
    const p2 = document.createElement("p");
    const a = document.createElement("a");
    a.href = BASE;
    a.target = "_blank";
    a.textContent = "Open Stroom →";
    p2.appendChild(a);
    el.appendChild(p2);
  }
}

async function init() {
  const tab = await currentTab();
  if (!tab || !tab.url || !/^https?:\/\//.test(tab.url)) {
    fatal("Deze pagina kan niet ingestuurd worden (geen normale http/https-URL).");
    return;
  }
  const url = tab.url;
  $("urlDisplay").textContent = url;
  $("title").value = tab.title || "";

  // Topics laden (faalt hier = inlogprobleem, meteen melden).
  let topics;
  try {
    topics = await getTopics();
  } catch (e) {
    fatal(e.message, true);
    return;
  }
  const sel = $("topic");
  sel.innerHTML = "";
  for (const t of topics) {
    const o = document.createElement("option");
    o.value = t.slug;
    o.textContent = t.name;
    sel.appendChild(o);
  }

  // UI tonen; titel is al gevuld met de tab-titel als fallback.
  $("loading").classList.add("hidden");
  $("form").classList.remove("hidden");

  // Metadata ophalen om titel/type/auteur/beschrijving te verbeteren.
  try {
    const meta = await fetchMeta(url);
    if (meta.title) $("title").value = meta.title;
    if (meta.format) $("format").value = meta.format;
    if (meta.author) $("author").value = meta.author;
    if (meta.description) $("description").value = meta.description;
  } catch (e) {
    // Niet fataal: de gebruiker kan alsnog handmatig invullen.
    setStatus("Kon metadata niet ophalen — vul handmatig aan. (" + e.message + ")", "err");
  }

  $("form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    doSubmit(url);
  });
  $("cancel").addEventListener("click", () => window.close());
}

async function doSubmit(url) {
  const title = $("title").value.trim();
  if (title.length < 3) {
    setStatus("Titel is verplicht (minimaal 3 tekens).", "err");
    return;
  }
  const btn = $("submit");
  btn.disabled = true;
  setStatus("Versturen…", "");
  try {
    const res = await submit({
      url,
      title,
      format: $("format").value,
      topic_slug: $("topic").value,
      author: $("author").value.trim() || null,
      description: $("description").value.trim() || null,
    });
    setStatus("✓ " + (res.message || "Toegevoegd aan inbox"), "ok");
    setTimeout(() => window.close(), 1200);
  } catch (e) {
    btn.disabled = false;
    setStatus(e.message, "err");
  }
}

document.addEventListener("DOMContentLoaded", init);
