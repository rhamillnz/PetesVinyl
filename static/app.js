/* Pete's Vinyl - front end. Plain JavaScript, no frameworks, no build step. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const app = $("#app");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, options = {}) {
  const opts = { headers: {}, ...options };
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch (_) { /* empty body */ }
  if (!resp.ok) {
    const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : resp.statusText;
    throw new Error(detail || "Something went wrong");
  }
  return data;
}

function money(value, currency = "NZD") {
  if (value === null || value === undefined || value === "" || isNaN(value)) return "—";
  const v = Number(value);
  const prefix = { NZD: "$", USD: "US$", AUD: "A$", GBP: "£", EUR: "€" }[currency] ?? currency + " ";
  return prefix + (Number.isInteger(v) ? v.toString() : v.toFixed(2));
}

let toastTimer;
$("#toast").addEventListener("click", () => { $("#toast").hidden = true; });
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 9000 : 5000);
}

function loadingHTML(message) {
  return `<div class="panel loading"><div class="big-disc spin"></div><div>${esc(message)}</div></div>`;
}

const store = {
  get(key, fallback = null) { try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* private mode */ } },
};

// ------------------------------------------------------------------ modal
function openModal(html, { wide = false } = {}) {
  const modal = $("#modal");
  const box = $("#modalBox");
  box.className = "modal-box" + (wide ? " wide" : "");
  box.innerHTML = html;
  modal.hidden = false;
  const first = box.querySelector("input, button, a");
  if (first) first.focus();
  return box;
}
function closeModal() { $("#modal").hidden = true; $("#modalBox").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").hidden) closeModal(); });

function confirmBox(message, yesLabel = "Yes", danger = false) {
  return new Promise((resolve) => {
    const box = openModal(`
      <h2>${esc(message)}</h2>
      <div class="row" style="margin-top:24px">
        <button class="btn ${danger ? "btn-red" : "btn-green"}" data-yes>${esc(yesLabel)}</button>
        <button class="btn btn-ghost" data-no>No, go back</button>
      </div>`);
    box.querySelector("[data-yes]").onclick = () => { closeModal(); resolve(true); };
    box.querySelector("[data-no]").onclick = () => { closeModal(); resolve(false); };
  });
}

function showPhoto(url) {
  openModal(`<img src="${esc(url)}" alt="Record photo"><div class="row" style="justify-content:center;margin-top:12px"><button class="btn" onclick="closeModal()">Close</button></div>`, { wide: true });
}

async function copyText(text, what) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  toast(`Copied the ${what}! Now click in the website box and press Ctrl + V to paste.`);
}

// ------------------------------------------------------------------ shared data
const CONDITIONS = [
  ["NM", "Like new", "Barely played"],
  ["VG+", "Very good", "Light wear, plays great"],
  ["VG", "Good", "Some crackle"],
  ["G+", "Well played", "Noticeable noise"],
  ["G", "Rough", "Heavily played"],
];
const COVER_CONDITIONS = [
  ["NM", "Like new", "Crisp and clean"],
  ["VG+", "Very good", "Light wear"],
  ["VG", "Good", "Some wear"],
  ["G+", "Well worn", "Noticeable wear"],
  ["G", "Rough", "Heavy wear"],
];
const STATE_LABEL = { collection: "In my collection", ready: "Ready to list", for_sale: "For sale", sold: "Sold" };
const STATUS_WORDS = { not_listed: "Not listed", ready: "Ready to paste", draft: "Draft saved", listed: "For sale ✅", sold: "Sold 🎉", ended: "Taken down" };
let platformsCache = null;

async function getPlatforms() {
  if (!platformsCache) platformsCache = (await api("/api/platforms")).platforms;
  return platformsCache;
}
function platformName(id) {
  const p = (platformsCache || []).find((x) => x.id === id);
  return p ? p.name : id;
}

async function refreshStats() {
  try {
    const s = await api("/api/stats");
    $("#stats").innerHTML = `
      <div class="stat"><b>${s.total}</b><span>Records</span></div>
      <div class="stat"><b>${s.for_sale}</b><span>For sale</span></div>
      <div class="stat"><b>${money(s.collection_value)}</b><span>Worth</span></div>
      <div class="stat"><b>${money(s.sold_total)}</b><span>Sold so far</span></div>`;
  } catch (_) { /* header stats are optional */ }
}

async function refreshBackup() {
  try {
    const b = await api("/api/backup");
    const dot = $("#backupDot");
    dot.className = "dot " + (!b.folder ? "bad" : b.last_result.startsWith("Backed up") ? "ok" : "warn");
    $("#backupBtn").title = b.last_backup ? `Last backed up ${b.last_backup}` : "Not backed up yet";
  } catch (_) { /* ignore */ }
}

$("#backupBtn").addEventListener("click", async () => {
  const btn = $("#backupBtn");
  btn.disabled = true;
  toast("Backing up to Google Drive…");
  try {
    const res = await api("/api/backup", { method: "POST" });
    toast(res.message, !res.ok);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
  refreshBackup();
});

$("#quitBtn").addEventListener("click", async () => {
  if (!(await confirmBox("Close Pete's Vinyl?", "Yes, close it", true))) return;
  toast("Saving a backup and closing…");
  let note = "";
  try {
    note = (await api("/api/quit", { method: "POST" })).message || "";
  } catch (e) {
    // A network error (TypeError) means the server has already gone, which is what we wanted.
    // Any other error means it did NOT close, so say so instead of pretending.
    if (!(e instanceof TypeError)) {
      toast(`It didn't close: ${e.message}. This may be an older copy of the app. Run Stop_PetesVinyl.bat instead.`, true);
      return;
    }
  }
  document.body.innerHTML = `
    <main style="min-height:100vh;display:grid;place-items:center;text-align:center">
      <div class="panel" style="max-width:640px">
        <div class="big-disc" style="margin:0 auto 20px"></div>
        <h1>Pete's Vinyl has closed.</h1>
        <p style="font-size:1.2rem">${note ? esc(note) + "<br>" : ""}You can now close this window.<br>
        To open it again, double-click <b>Pete's Vinyl</b> on the desktop.</p>
      </div></main>`;
  setTimeout(() => window.close(), 800);
});

// ------------------------------------------------------------------ router
const flags = { identify: new Set(), value: new Set() };
let cleanup = null;

async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  closeModal();
  refreshStats();
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  window.scrollTo(0, 0);
  try {
    if (parts[0] === "add") return await renderPhotos(null);
    if (parts[0] === "settings") return await renderSettings();
    if (parts[0] === "logs") return await renderLogs();
    if (parts[0] === "record" && parts[1]) {
      const id = Number(parts[1]);
      const page = parts[2] || "";
      if (page === "photos") return await renderPhotos(id);
      if (page === "details") return await renderDetails(id);
      if (page === "price") return await renderPrice(id);
      if (page === "sell") return await renderSell(id);
      return await renderRecord(id);
    }
    return await renderHome();
  } catch (e) {
    if (e.message === "Not Found") showRestartBanner();
    const stale = e.message === "Not Found"
      ? "This page needs a newer version of the app than the one that's running. Please restart Pete's Vinyl (see the message at the top)."
      : e.message;
    app.innerHTML = `<div class="panel"><h2>Oops, something went wrong</h2><p>${esc(stale)}</p><a class="btn" href="#/">Back to my records</a></div>`;
  }
}
window.addEventListener("hashchange", route);

function stepsBar(id, current) {
  const steps = [["photos", "Photos"], ["details", "Check details"], ["price", "Price"], ["sell", "Sell"]];
  const idx = steps.findIndex((s) => s[0] === current);
  return `<nav class="steps" aria-label="Steps">${steps.map(([key, label], i) => {
    const cls = i < idx ? "done" : i === idx ? "current" : "";
    const inner = `<span class="num">${i < idx ? "✓" : i + 1}</span>${label}`;
    return id ? `<a class="step ${cls}" href="#/record/${id}/${key}">${inner}</a>` : `<span class="step ${cls}">${inner}</span>`;
  }).join("")}</nav>`;
}

// ------------------------------------------------------------------ HOME: the jukebox wall
const home = { state: store.get("pv.filter", ""), q: "" };

async function renderHome() {
  app.innerHTML = loadingHTML("Loading your records…");
  const data = await api(`/api/records?q=${encodeURIComponent(home.q)}`);
  await getPlatforms();
  const all = data.records;
  const counts = { "": all.length, collection: 0, ready: 0, for_sale: 0, sold: 0 };
  all.forEach((r) => { counts[r.state] += 1; });
  counts.collection += counts.ready;
  const shown = all.filter((r) => !home.state || r.state === home.state || (home.state === "collection" && r.state === "ready"));
  const tabs = [["", "All"], ["collection", "In my collection"], ["for_sale", "For sale"], ["sold", "Sold"]];

  app.innerHTML = `
    <div class="home-bar">
      <a class="btn btn-huge" href="#/add">➕ Add a Record</a>
      <input class="search" id="search" type="search" placeholder="🔍  Find a record…" value="${esc(home.q)}" aria-label="Find a record">
    </div>
    <div class="home-bar">
      <div class="tabs" role="group" aria-label="Show">
        ${tabs.map(([key, label]) => `<button class="tab" data-state="${key}" aria-pressed="${home.state === key}">${label} (${counts[key]})</button>`).join("")}
      </div>
    </div>
    ${shown.length ? jukeboxHTML(shown) : emptyHTML(all.length)}`;

  $$(".tab").forEach((t) => t.addEventListener("click", () => { home.state = t.dataset.state; store.set("pv.filter", home.state); renderHome(); }));
  let timer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(async () => { home.q = e.target.value; await renderHome(); const s = $("#search"); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }, 350);
  });
  $$(".letter-bar button[data-letter]").forEach((b) => b.addEventListener("click", () => {
    const target = document.getElementById(`letter-${b.dataset.letter}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  refreshStats();
}

// Sort key: artist then album, ignoring case and a leading "The ". Unnamed records go last, under "?".
function sortKey(r) {
  const clean = (t) => (t || "").trim().toLowerCase().replace(/^(the|a|an)\s+/, "");
  return `${clean(r.artist) || "\uffff"}\u0000${clean(r.album_title)}`;
}
function letterOf(r) {
  const c = ((r.artist || "").trim().toLowerCase().replace(/^(the|a|an)\s+/, "")[0] || "").toUpperCase();
  if (!c) return "?";
  return /[A-Z]/.test(c) ? c : "#";
}

// A Wurlitzer-style selection window: records in A-Z order, each with a selection code like A1, A2, B1...
function jukeboxHTML(records) {
  const sorted = [...records].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const groups = new Map();
  sorted.forEach((r) => {
    const l = letterOf(r);
    if (!groups.has(l)) groups.set(l, []);
    groups.get(l).push(r);
  });
  const letters = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ#?"];
  const bar = letters.map((l) => groups.has(l)
    ? `<button type="button" data-letter="${l === "#" ? "num" : l === "?" ? "unknown" : l}" title="Jump to ${l}">${l}</button>`
    : `<span class="off">${l}</span>`).join("");
  const anchor = (l) => (l === "#" ? "num" : l === "?" ? "unknown" : l);
  const sections = [...groups.entries()].map(([l, list]) => `
    <section class="letter-group" id="letter-${anchor(l)}">
      <h2 class="letter-heading"><span>${l === "?" ? "Not named yet" : l}</span></h2>
      <div class="wall">${list.map((r, i) => cardHTML(r, `${l === "?" ? "•" : l}${i + 1}`)).join("")}</div>
    </section>`).join("");
  return `<div class="jukebox-window">
    <div class="letter-bar" role="navigation" aria-label="Jump to a letter">${bar}</div>
    ${sections}
  </div><div class="grille" aria-hidden="true"></div>`;
}

function emptyHTML(total) {
  if (total) return `<div class="panel empty"><h2>No records here</h2><p>Try another button above, or clear the search box.</p></div>`;
  return `<div class="panel empty"><div class="big-disc"></div><h2>Welcome, ${esc(settingsName())}!</h2>
    <p style="font-size:1.2rem">You haven't added any records yet.<br>Press the big gold <b>Add a Record</b> button to start.</p></div>`;
}
function settingsName() { return store.get("pv.name", "Pete"); }

function cardHTML(r, code = "") {
  const img = r.images.front ? `<img src="${esc(r.images.front)}" alt="" loading="lazy">` : "";
  const listedOn = (platformsCache || []).filter((p) => r[`${p.id}_status`] === "listed").map((p) => p.name);
  let badge = `<span class="badge ${r.state}">${STATE_LABEL[r.state]}</span>`;
  let price = r.suggested_price ? money(r.suggested_price) : "";
  if (r.state === "sold") price = money(r.sold_price);
  return `
    <a class="card" href="#/record/${r.id}">
      <div class="card-img">${img}${r.state === "sold" ? `<div class="sold-stamp">SOLD ${money(r.sold_price)}</div>` : ""}</div>
      <div class="strip">
        ${code ? `<span class="code">${esc(code)}</span>` : ""}
        <div class="artist">${esc(r.artist || "Unknown artist")}</div>
        <div class="album">${esc(r.album_title || "Untitled")}</div>
      </div>
      <div class="card-foot">${badge}<span>${price}</span></div>
      ${listedOn.length ? `<div class="sites">On: ${esc(listedOn.join(", "))}</div>` : ""}
    </a>`;
}

// ------------------------------------------------------------------ STEP 1: photos
const SLOTS = [
  { key: "front", label: "Front cover", say: "the FRONT COVER", tip: "Hold the record sleeve up so it fills the picture.", icon: "🖼️" },
  { key: "back", label: "Back cover", say: "the BACK COVER", tip: "Turn the sleeve over. Make sure the small writing is in focus.", icon: "📜" },
  { key: "disc_a", label: "Side A label", say: "the SIDE A LABEL", tip: "Take the record out and show the middle label of Side A.", icon: "💿" },
  { key: "disc_b", label: "Side B label", say: "the SIDE B LABEL", tip: "Flip the record over and show the Side B label.", icon: "💿" },
];

async function renderPhotos(id) {
  const rec = id ? await api(`/api/records/${id}`) : null;
  const shots = {};          // new photos taken this visit (data URLs)
  const existing = { ...(rec ? rec.images : {}) };
  const slots = [...SLOTS];  // the four standard photos, plus any extras (more discs, inserts, close-ups)
  let extraSeq = 0;
  let discCount = rec ? rec.disc_count : 1;
  ((rec && rec.extras) || []).forEach((e) => {
    extraSeq = Math.max(extraSeq, Number(e.key.split("_")[1]));
    slots.push({ key: e.key, label: e.label, say: e.label, tip: "Tap the red button to retake this photo.", icon: "📷", extra: true });
    existing[e.key] = e.url;
  });
  let current = 0;
  let stream = null;

  app.innerHTML = `
    ${stepsBar(id, "photos")}
    <div class="grid-2">
      <div>
        <div class="camera-frame">
          <video id="video" autoplay playsinline muted></video>
          <div class="flash" id="flash"></div>
          <div class="camera-msg" id="camMsg">Starting the camera…</div>
        </div>
        <div class="thumbs" id="thumbs"></div>
        <div class="extras-bar">
          <span class="label">More to photograph?</span>
          <button class="btn btn-chrome btn-small" data-extra="disc">💿 Another record in the cover</button>
          <button class="btn btn-chrome btn-small" data-extra="art">🖼️ Poster, insert or artwork</button>
          <button class="btn btn-chrome btn-small" data-extra="inner">📄 Inner sleeve</button>
          <button class="btn btn-chrome btn-small" data-extra="damage">🔍 Close-up of a scratch or crease</button>
        </div>
      </div>
      <div class="panel">
        <div class="instruction" id="instruction"></div>
        <button class="btn btn-huge btn-block btn-red" id="snap">📷 Take Photo</button>
        <p class="muted" style="text-align:center">or press the <span class="kbd">Space bar</span></p>
        <button class="btn btn-huge btn-block btn-green" id="next" style="margin-top:14px">${id ? "Save photos ✓" : "Next: Look it up ➜"}</button>
        <div class="row" style="margin-top:22px;justify-content:center">
          <label class="btn btn-ghost btn-small">🖼️ Use a saved picture instead
            <input type="file" id="upload" accept="image/*" hidden>
          </label>
          <a class="btn btn-ghost btn-small" href="${id ? `#/record/${id}` : "#/"}">Cancel</a>
        </div>
      </div>
    </div>`;

  function addExtra(kind) {
    const add = (label, say, tip, icon) => {
      extraSeq += 1;
      slots.push({ key: `extra_${extraSeq}`, label, say, tip, icon, extra: true });
      current = slots.length - 1;
    };
    if (kind === "disc") {
      discCount += 1;
      add(`Disc ${discCount} - Side A`, `DISC ${discCount}, SIDE A label`, "Take the next record out of the cover and show the Side A label.", "💿");
      add(`Disc ${discCount} - Side B`, `DISC ${discCount}, SIDE B label`, "Flip it over and show the Side B label.", "💿");
      current = slots.length - 2;
    } else if (kind === "art") {
      add("Poster / insert / artwork", "the POSTER, INSERT or ARTWORK", "Show anything extra that came with the record: poster, booklet, lyric sheet or printed inner.", "🖼️");
    } else if (kind === "inner") {
      add("Inner sleeve", "the INNER SLEEVE", "Show the paper or plastic sleeve the record sits in.", "📄");
    } else {
      add("Close-up of damage", "a CLOSE-UP of the scratch or crease", "Hold the damage close to the camera in good light so buyers can see exactly what it is.", "🔍");
    }
    paint();
  }
  // Give the keyboard back to the camera afterwards, so Space takes the photo instead of pressing this button again.
  $$("[data-extra]").forEach((b) => b.addEventListener("click", () => { addExtra(b.dataset.extra); b.blur(); }));

  async function removeCurrentExtra() {
    const slot = slots[current];
    if (!slot.extra) return;
    if (existing[slot.key] && !(await confirmBox(`Delete the photo "${slot.label}" for good?`, "Yes, delete it", true))) return;
    if (existing[slot.key] && id) await api(`/api/records/${id}/extra/${slot.key}`, { method: "DELETE" });
    delete existing[slot.key]; delete shots[slot.key];
    slots.splice(current, 1);
    current = Math.min(current, slots.length - 1);
    paint();
  }

  function paint() {
    const slot = slots[current];
    $("#instruction").innerHTML = `
      <div class="muted" style="color:#6b4a2a;font-weight:700">Photo ${current + 1} of ${slots.length}</div>
      <div class="which">${slot.icon} Show me ${esc(slot.say)}</div>
      <div style="margin-top:8px;font-size:1.05rem">${esc(slot.tip)}</div>
      ${slot.extra ? `<button type="button" class="btn btn-ghost btn-small" id="dropExtra" style="margin-top:10px;color:#6b1a10;border-color:#6b1a10">✕ I don't need this photo</button>` : ""}`;
    if (slot.extra) $("#dropExtra").addEventListener("click", removeCurrentExtra);
    $("#thumbs").innerHTML = slots.map((s, i) => {
      const url = shots[s.key] || existing[s.key];
      return `<button class="thumb ${i === current ? "active" : ""} ${url ? "has" : ""}" data-i="${i}" title="${url ? "Click to retake" : "Click to take this one"}">
        <span class="pic">${url ? `<img src="${esc(url)}" alt="">` : s.icon}</span>
        <span class="lbl">${url ? "✓ " : ""}${s.label}</span></button>`;
    }).join("");
    $$(".thumb").forEach((b) => b.addEventListener("click", () => { current = Number(b.dataset.i); paint(); b.blur(); }));
    const haveFront = shots.front || existing.front;
    $("#next").disabled = !haveFront && !Object.keys(shots).length;
  }

  function addShot(dataUrl) {
    shots[slots[current].key] = dataUrl;
    const nextEmpty = slots.findIndex((s) => !shots[s.key] && !existing[s.key]);
    if (nextEmpty === -1) {
      toast("All the photos are done! Add more if there's another record or a poster, or press the green button.");
      $("#next").focus();
    } else {
      current = nextEmpty;
    }
    paint();
  }

  async function startCamera() {
    const deviceId = store.get("pv.camera");
    const video = { width: { ideal: 1920 }, height: { ideal: 1080 } };
    if (deviceId) video.deviceId = { exact: deviceId };
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (e) {
      if (deviceId) { store.set("pv.camera", ""); return startCamera(); }
      $("#camMsg").innerHTML = `<div>📷 I can't see the camera.<br><span class="muted">Check it's plugged in, then press Try Again. If the browser asks, click <b>Allow</b>.</span><br><br>
        <button class="btn" id="retryCam">Try Again</button></div>`;
      $("#retryCam").onclick = startCamera;
      return;
    }
    const v = $("#video");
    if (!v) { stream.getTracks().forEach((t) => t.stop()); return; }
    v.srcObject = stream;
    $("#camMsg").classList.add("hidden");
  }

  function snap() {
    const v = $("#video");
    if (!stream || !v.videoWidth) { toast("The camera isn't ready yet.", true); return; }
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth; canvas.height = v.videoHeight;
    canvas.getContext("2d").drawImage(v, 0, 0);
    const f = $("#flash"); f.classList.remove("go"); void f.offsetWidth; f.classList.add("go");
    shutterSound();
    addShot(canvas.toDataURL("image/jpeg", 0.9));
  }

  $("#snap").addEventListener("click", snap);
  $("#upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (file) addShot(await fileToJpeg(file));
    e.target.value = "";
  });
  const onKey = (e) => {
    if (e.code === "Space" && !["INPUT", "TEXTAREA", "BUTTON", "SELECT"].includes(document.activeElement.tagName)) {
      e.preventDefault(); snap();
    }
  };
  document.addEventListener("keydown", onKey);

  const labelsFor = () => Object.fromEntries(slots.filter((x) => x.extra && shots[x.key]).map((x) => [x.key, x.label]));
  $("#next").addEventListener("click", async () => {
    const btn = $("#next");
    btn.disabled = true; btn.textContent = "Saving…";
    try {
      if (id) {
        if (Object.keys(shots).length || discCount !== rec.disc_count) await api(`/api/records/${id}`, { method: "PUT", body: { images: shots, extra_labels: labelsFor(), disc_count: discCount } });
        toast("Photos saved.");
        location.hash = `#/record/${id}`;
      } else {
        const created = await api("/api/records", { method: "POST", body: { images: shots, extra_labels: labelsFor(), disc_count: discCount, is_first_owner: true } });
        flags.identify.add(created.id);
        location.hash = `#/record/${created.id}/details`;
      }
    } catch (e) {
      toast(e.message, true);
      btn.disabled = false; btn.textContent = "Try saving again";
    }
  });

  cleanup = () => {
    document.removeEventListener("keydown", onKey);
    if (stream) stream.getTracks().forEach((t) => t.stop());
  };
  paint();
  startCamera();
}

function shutterSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator(); const gain = ctx.createGain();
    osc.type = "square"; osc.frequency.value = 900;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);
    osc.connect(gain).connect(ctx.destination); osc.start(); osc.stop(ctx.currentTime + 0.12);
    setTimeout(() => ctx.close(), 300);
  } catch (_) { /* no sound is fine */ }
}

function fileToJpeg(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1920 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.9));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

// ------------------------------------------------------------------ STEP 2: check details
async function renderDetails(id) {
  let aiInfo = null;
  let matches = [];
  let rec;
  let pre = null;
  if (!flags.identify.has(id)) {
    // Photos but no name yet (e.g. opened from the record page)? Let the AI have a look automatically.
    pre = await api(`/api/records/${id}`);
    if (!pre.artist && !pre.album_title && pre.images.front && !pre.ai_summary) flags.identify.add(id);
  }
  if (flags.identify.has(id)) {
    flags.identify.delete(id);
    app.innerHTML = stepsBar(id, "details") + loadingHTML("Having a good look at your record… this can take up to a minute.");
    const res = await api(`/api/records/${id}/identify`, { method: "POST" });
    rec = res.record; aiInfo = res.ai; matches = res.discogs_matches || [];
  } else {
    rec = pre;
  }
  paintDetails(id, rec, aiInfo, matches);
}

function paintDetails(id, rec, aiInfo, matches) {
  const field = (key, label, hint = "") => `
    <div class="field"><label for="f_${key}">${label}</label>
      <input type="text" id="f_${key}" name="${key}" value="${esc(rec[key])}">
      ${hint ? `<span class="hint">${hint}</span>` : ""}</div>`;
  const condPicker = (key, label, options = CONDITIONS) => `
    <div class="field"><span class="label">${label}</span>
      <div class="choices" data-cond="${key}">${options.map(([code, word, sub]) =>
        `<button type="button" class="choice" data-code="${code}" aria-pressed="${(rec[key] || "VG+") === code}">${word}<small>${sub}</small></button>`).join("")}</div></div>`;

  const choiceGroup = (key, label, options) => `
    <div class="field"><span class="label">${label}</span>
      <div class="choices" data-cond="${key}">${options.map(([code, word, sub]) =>
        `<button type="button" class="choice" data-code="${code}" aria-pressed="${rec[key] === code}">${word}<small>${sub}</small></button>`).join("")}</div></div>`;
  const issueChips = ISSUE_OPTIONS.map(([code, word]) =>
    `<button type="button" class="choice chip" data-issue="${code}" aria-pressed="${(rec.cover_issues || []).includes(code)}">${word}</button>`).join("");
  detailsDiscs = rec.disc_count || 1;
  let aiBox = "";
  if (aiInfo && aiInfo.error) {
    aiBox = `<div class="ai-box warn"><span class="icon">✍️</span><div>${esc(aiInfo.error)}</div></div>`;
  } else if (aiInfo || rec.ai_summary) {
    const conf = aiInfo && aiInfo.confidence ? ` <span class="badge ${aiInfo.confidence === "high" ? "for_sale" : "ready"}">${esc(aiInfo.confidence)} confidence</span>` : "";
    aiBox = `<div class="ai-box"><span class="icon">🤖</span><div><b>Here's what I found.</b>${conf}<br>${esc((aiInfo && aiInfo.explanation) || rec.ai_summary)}<br>
      <span class="muted">Please check the details below and fix anything that's wrong.</span></div></div>`;
  }

  app.innerHTML = `
    ${stepsBar(id, "details")}
    <div class="grid-2">
      <form class="panel" id="detailsForm" autocomplete="off">
        ${aiBox}
        <div class="form-grid">
          ${field("artist", "Artist / Band")}
          ${field("album_title", "Album title")}
          ${field("year_pressed", "Year this copy was pressed", "Check the small print on the label or back cover.")}
          ${field("pressing_location", "Where it was pressed", "For example: New Zealand, UK, USA")}
        </div>
        <label class="check-big"><input type="checkbox" id="firstOwner" ${rec.is_first_owner ? "checked" : ""}> I'm the first owner (I bought it new)</label>
        <div class="field ${rec.is_first_owner ? "hidden" : ""}" id="ownersField">
          <span class="label">How many owners has it had, counting you?</span>
          <div class="stepper">
            <button type="button" class="btn btn-small" id="ownMinus" aria-label="Fewer">−</button>
            <span class="val" id="ownVal">${Math.max(2, rec.number_of_owners || 2)}</span>
            <button type="button" class="btn btn-small" id="ownPlus" aria-label="More">+</button>
          </div>
        </div>
        <div class="field"><span class="label">How many records are in the cover?</span>
          <div class="stepper">
            <button type="button" class="btn btn-small" id="discMinus" aria-label="Fewer">−</button>
            <span class="val" id="discVal">${detailsDiscs}</span>
            <button type="button" class="btn btn-small" id="discPlus" aria-label="More">+</button>
          </div>
          <span class="hint">A double album has 2. Take a photo of each disc's labels on the photos step.</span></div>
        <div class="cond-block"><h3>💿 The RECORD (the vinyl itself)</h3>
          ${choiceGroup("media_scratches", "Is it scratched?", [["none", "Not at all", "Looks clean"], ["light", "A little", "Hairline marks"], ["some", "Some", "Visible scratches"], ["deep", "Badly", "You can feel them"]])}
          ${choiceGroup("media_play", "How does it play?", [["perfect", "Perfectly", "Silent"], ["crackle", "Slight crackle", "A little noise"], ["noisy", "Noisy", "Clicks and pops"], ["skips", "Skips", "Jumps or repeats"]])}
          ${condPicker("condition_media", "Overall grade (picked for you, change it if you like)")}
        </div>
        <div class="cond-block"><h3>🖼️ The COVER (dust cover / sleeve)</h3>
          ${choiceGroup("cover_creases", "Is it creased?", [["none", "Not at all", "Flat and crisp"], ["slight", "Slightly", "Small creases"], ["noticeable", "Noticeably", "Clear creases"], ["bad", "Badly", "Heavily creased"]])}
          <div class="field"><span class="label">Anything else wrong with the cover?</span><div class="choices">${issueChips}</div></div>
          ${condPicker("condition_sleeve", "Overall grade (picked for you, change it if you like)", COVER_CONDITIONS)}
        </div>
        <details class="more"><summary>More details (optional)</summary>
          <div class="form-grid">
            ${field("label", "Record label")}
            ${field("catalog_number", "Catalogue number")}
            ${field("original_year", "First released")}
            ${field("barcode", "Barcode")}
          </div>
          ${field("matrix_numbers", "Numbers scratched near the middle (matrix)")}
          <div class="field"><label for="f_notes">Notes for buyers</label>
            <textarea id="f_notes" name="notes" placeholder="e.g. Includes original inner sleeve and poster">${esc(rec.notes)}</textarea></div>
        </details>
        <button class="btn btn-huge btn-block btn-green" type="submit">Looks right - check the price ➜</button>
        <div class="row" style="margin-top:14px;justify-content:center">
          <button class="btn btn-ghost btn-small" type="button" id="justSave">Just save it to my collection</button>
        </div>
      </form>
      <div class="panel">
        <h2>Which one is yours?</h2>
        <p class="muted">These are records on Discogs that match. Tap the one that looks like yours to fill in the details.</p>
        <div id="matchArea">${matchesHTML(matches, rec)}</div>
        <button class="btn btn-small btn-chrome" id="findMatches">🔍 Search Discogs again</button>
        <button class="btn btn-small btn-chrome" id="askAI">🤖 Read the photos again</button>
        <div class="photos-big" style="margin-top:22px">${SLOTS.map((s) => rec.images[s.key]
          ? `<button type="button" data-photo="${esc(rec.images[s.key])}"><img src="${esc(rec.images[s.key])}" alt="${s.label}"></button>`
          : `<button type="button" disabled><span class="none">No ${s.label.toLowerCase()}</span></button>`).join("")}</div>
      </div>
    </div>`;

  let owners = Math.max(2, rec.number_of_owners || 2);
  $("#firstOwner").addEventListener("change", (e) => $("#ownersField").classList.toggle("hidden", e.target.checked));
  $("#ownMinus").addEventListener("click", () => { owners = Math.max(2, owners - 1); $("#ownVal").textContent = owners; });
  $("#ownPlus").addEventListener("click", () => { owners = Math.min(20, owners + 1); $("#ownVal").textContent = owners; });
  $("#discMinus").addEventListener("click", () => { detailsDiscs = Math.max(1, detailsDiscs - 1); $("#discVal").textContent = detailsDiscs; });
  $("#discPlus").addEventListener("click", () => { detailsDiscs = Math.min(20, detailsDiscs + 1); $("#discVal").textContent = detailsDiscs; });
  $$(".choices[data-cond]").forEach((group) => group.addEventListener("click", (e) => {
    const b = e.target.closest(".choice"); if (!b) return;
    $$(".choice", group).forEach((x) => x.setAttribute("aria-pressed", x === b));
    autoGrade();
  }));
  $$(".chip").forEach((chip) => chip.addEventListener("click", () => {
    chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") !== "true");
    autoGrade();
  }));
  $$("[data-photo]").forEach((b) => b.addEventListener("click", () => showPhoto(b.dataset.photo)));
  bindMatches(id);
  $("#askAI").addEventListener("click", async () => {
    await saveDetails(id, owners);
    flags.identify.add(id);
    renderDetails(id);
  });
  $("#findMatches").addEventListener("click", async () => {
    await saveDetails(id, owners);
    $("#matchArea").innerHTML = loadingHTML("Searching Discogs…");
    const res = await api(`/api/records/${id}/discogs-matches`);
    const fresh = await api(`/api/records/${id}`);
    $("#matchArea").innerHTML = res.configured ? matchesHTML(res.matches, fresh)
      : `<p class="muted">Discogs isn't connected yet. Ask for a Discogs token to be added in Settings ⚙️.</p>`;
    bindMatches(id);
  });

  $("#detailsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveDetails(id, owners);
    flags.value.add(id);
    location.hash = `#/record/${id}/price`;
  });
  $("#justSave").addEventListener("click", async () => {
    await saveDetails(id, owners);
    toast("Saved to your collection.");
    location.hash = `#/record/${id}`;
  });
}

function matchesHTML(matches, rec) {
  if (!matches || !matches.length) return `<p class="muted">No matches to show yet.</p>`;
  return `<div class="matches">${matches.map((m) => `
    <button type="button" class="match" data-release="${esc(m.id)}" aria-pressed="${String(rec.discogs_release_id) === String(m.id)}">
      ${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy">` : ""}
      <b>${esc(m.title)}</b><br>${esc(m.year || "")} · ${esc(m.country || "")}<br>${esc(m.catno || "")}
    </button>`).join("")}</div>`;
}

function bindMatches(id) {
  $$(".match").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const rec = await api(`/api/records/${id}/discogs-match`, { method: "POST", body: { release_id: b.dataset.release } });
      toast("Got it! I've filled in the details from Discogs.");
      const matches = $$(".match").map((m) => ({ id: m.dataset.release, title: m.querySelector("b").textContent, thumb: (m.querySelector("img") || {}).src, year: "", country: "", catno: "" }));
      paintDetails(id, rec, null, matches);
    } catch (e) { toast(e.message, true); b.disabled = false; }
  }));
}

let detailsDiscs = 1;
const ISSUE_OPTIONS = [["seam_split", "Split seam"], ["ring_wear", "Ring wear"], ["writing", "Writing or stamp"], ["stain", "Stain or mould"], ["tear", "Tear"]];
const SCRATCH_W = { none: "no scratches", light: "light scratches", some: "some scratches", deep: "deep scratches" };
const PLAY_W = { perfect: "plays perfectly", crackle: "slight crackle", noisy: "noisy (clicks and pops)", skips: "skips" };
const CREASE_W = { none: "no creases", slight: "slight creasing", noticeable: "noticeable creases", bad: "heavily creased" };
const ISSUE_W = Object.fromEntries(ISSUE_OPTIONS.map(([c, w]) => [c, w.toLowerCase()]));

// Suggest the overall grades from the scratch / play / crease answers (Pete can still tap a different grade).
function autoGrade() {
  const pressed = (k) => { const g = $(`.choices[data-cond="${k}"]`); const b = g && $(".choice[aria-pressed='true']", g); return b ? b.dataset.code : ""; };
  const setGrade = (key, code) => $$(`.choices[data-cond="${key}"] .choice`).forEach((x) => x.setAttribute("aria-pressed", x.dataset.code === code));
  const sc = { none: 0, light: 1, some: 2, deep: 3 }[pressed("media_scratches")];
  const pl = { perfect: 0, crackle: 1, noisy: 2, skips: 4 }[pressed("media_play")];
  if (sc !== undefined && pl !== undefined) {
    const t = sc + pl;
    setGrade("condition_media", t === 0 ? "NM" : t <= 2 ? "VG+" : t <= 4 ? "VG" : t <= 6 ? "G+" : "G");
  }
  const cr = { none: 0, slight: 1, noticeable: 2, bad: 3 }[pressed("cover_creases")];
  if (cr !== undefined) {
    const t = cr + Math.min($$(".chip[aria-pressed='true']").length, 3) * 0.5;
    setGrade("condition_sleeve", t === 0 ? "NM" : t <= 1.5 ? "VG+" : t <= 2.5 ? "VG" : t <= 3.5 ? "G+" : "G");
  }
}

async function saveDetails(id, owners) {
  const form = $("#detailsForm");
  const body = {};
  $$("input[name], textarea[name]", form).forEach((el) => { body[el.name] = el.value.trim(); });
  body.is_first_owner = $("#firstOwner").checked;
  body.number_of_owners = body.is_first_owner ? 1 : owners;
  body.disc_count = detailsDiscs;
  body.cover_issues = $$(".chip[aria-pressed='true']", form).map((b) => b.dataset.issue);
  $$(".choices", form).forEach((g) => {
    const on = $(".choice[aria-pressed='true']", g);
    if (on) body[g.dataset.cond] = on.dataset.code;
  });
  return api(`/api/records/${id}`, { method: "PUT", body });
}

// ------------------------------------------------------------------ STEP 3: price
async function renderPrice(id) {
  let rec = await api(`/api/records/${id}`);
  let val = null;
  if (flags.value.has(id) || !rec.valued_at) {
    flags.value.delete(id);
    app.innerHTML = stepsBar(id, "price") + loadingHTML("Checking what this record sells for… this can take up to a minute.");
    try {
      val = await api("/api/estimate-value", { method: "POST", body: { record_id: id } });
    } catch (e) { toast(e.message, true); }
    rec = await api(`/api/records/${id}`);
  }
  const notes = (val ? val.notes : (rec.valuation_notes || "").split("\n")).filter(Boolean);
  const tile = (amount, label) => `<div class="value-tile"><div class="amt">${money(amount)}</div><div class="src">${label}</div></div>`;

  app.innerHTML = `
    ${stepsBar(id, "price")}
    <div class="panel">
      <h1>${esc(rec.artist)} — ${esc(rec.album_title)}</h1>
      <div class="value-tiles">
        ${tile(rec.discogs_median, "Discogs price")}
        ${tile(rec.popsike_median, "Popsike past auctions")}
        ${tile(rec.ebay_sold_average, "eBay recent sales")}
        ${tile(rec.ai_estimate, "Internet research")}
      </div>
      <div class="check-links" id="checkLinks"></div>
      <div class="price-hero">
        <div style="font-weight:700">I suggest listing it for</div>
        <div class="big">${money(rec.suggested_price)}</div>
        <label style="display:block;margin-top:10px">Want a different price? Type it here:<br>
          <input type="number" min="1" step="1" id="priceInput" value="${rec.suggested_price ?? ""}"></label>
      </div>
      ${notes.length ? `<ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      <div class="row">
        <button class="btn btn-huge btn-green" id="toSell">Sell it ➜</button>
        <button class="btn btn-chrome" id="again">🔄 Check the price again</button>
        <span class="spacer"></span>
        <button class="btn btn-ghost" id="keep">Keep it in my collection</button>
      </div>
    </div>`;

  const savePrice = async () => {
    const p = Number($("#priceInput").value);
    if (p > 0 && p !== rec.suggested_price) await api(`/api/records/${id}`, { method: "PUT", body: { suggested_price: p } });
  };
  api(`/api/records/${id}/price-links`).then((l) => {
    const el = $("#checkLinks"); if (!el) return;
    el.innerHTML = `<span class="label">See the real sold prices yourself:</span>
      <a class="btn btn-chrome btn-small" href="${esc(l.popsike)}" target="_blank" rel="noopener">🔎 Popsike</a>
      <a class="btn btn-chrome btn-small" href="${esc(l.ebay)}" target="_blank" rel="noopener">🔎 eBay sold items</a>
      ${l.discogs ? `<a class="btn btn-chrome btn-small" href="${esc(l.discogs)}" target="_blank" rel="noopener">🔎 Discogs sales history</a>` : ""}`;
  }).catch(() => {});
  $("#again").addEventListener("click", () => { flags.value.add(id); renderPrice(id); });
  $("#toSell").addEventListener("click", async () => {
    await savePrice();
    if (!Number($("#priceInput").value)) { toast("Please type a price first.", true); return; }
    location.hash = `#/record/${id}/sell`;
  });
  $("#keep").addEventListener("click", async () => { await savePrice(); toast("Saved to your collection."); location.hash = `#/record/${id}`; });
}

// ------------------------------------------------------------------ STEP 4: sell
async function renderSell(id) {
  const rec = await api(`/api/records/${id}`);
  const platforms = (await getPlatforms()).filter((p) => p.enabled);
  const recommended = rec.recommended_platforms && rec.recommended_platforms.length ? rec.recommended_platforms : platforms.slice(0, 2).map((p) => p.id);
  const chosen = new Set(recommended);

  app.innerHTML = `
    ${stepsBar(id, "sell")}
    <div class="panel">
      <h1>Where shall we sell it?</h1>
      <p style="font-size:1.1rem">I've ticked the best places for a record worth about <b>${money(rec.suggested_price)}</b>. Tap a box to tick or untick it.</p>
      <div class="site-grid">${platforms.map((p) => `
        <button class="site" data-p="${p.id}" aria-pressed="${chosen.has(p.id)}">
          ${recommended.includes(p.id) ? `<span class="star">⭐ Best choice</span>` : ""}
          <div class="name">${esc(p.name)}</div><div class="muted">${esc(p.where)}</div>
        </button>`).join("")}</div>
      <button class="btn btn-huge btn-block btn-green" id="go">🚀 Get it listed!</button>
    </div>
    <div class="helper" id="helper"></div>`;

  $$(".site").forEach((b) => b.addEventListener("click", () => {
    const p = b.dataset.p;
    chosen.has(p) ? chosen.delete(p) : chosen.add(p);
    b.setAttribute("aria-pressed", chosen.has(p));
  }));
  $("#go").addEventListener("click", async () => {
    if (!chosen.size) { toast("Please tick at least one place to sell.", true); return; }
    const btn = $("#go");
    btn.disabled = true;
    $("#helper").innerHTML = loadingHTML("Getting your listings ready…");
    try {
      const res = await api("/api/syndicate", { method: "POST", body: { record_id: id, platforms: [...chosen] } });
      $("#helper").innerHTML = `<h2 style="margin-top:10px">Your listings</h2>` +
        Object.values(res.results).map((r) => helperCardHTML(r.listing, r)).join("") +
        `<a class="btn btn-huge btn-block" href="#/record/${id}">All done ✓</a>`;
      bindHelpers(id);
      $("#helper").scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      $("#helper").innerHTML = "";
      toast(e.message, true);
    }
    btn.disabled = false;
  });
}

function helperCardHTML(listing, result = null) {
  const status = result ? result.status : listing.status;
  const auto = result && result.automatic;
  const link = (result && result.url) || listing.link;
  const done = status === "listed" || status === "draft";
  const assist = ["facebook", "gumtree", "trademe", "ebay"].includes(listing.platform);
  return `
    <div class="helper-card ${done ? "done" : ""}" data-platform="${listing.platform}">
      <h3>${esc(listing.name)} <span class="badge ${done ? "for_sale" : "ready"}">${STATUS_WORDS[status] || status}</span></h3>
      ${result ? `<p>${esc(result.message)}</p>` : ""}
      ${auto && link ? `<p><a class="btn btn-green" href="${esc(link)}" target="_blank" rel="noopener">See it on ${esc(listing.name)} ↗</a></p>` : ""}
      ${auto ? "" : `
        <p class="muted">${esc(listing.tip)}</p>
        <div class="copy-row"><span class="what">Title</span><div class="box">${esc(listing.title)}</div>
          <button class="btn btn-small" data-copy="title">📋 Copy</button></div>
        <div class="copy-row"><span class="what">Price</span><div class="box">${esc(String(listing.price))} ${esc(listing.currency)}</div>
          <button class="btn btn-small" data-copy="price">📋 Copy</button></div>
        <div class="copy-row"><span class="what">Description</span><div class="box">${esc(listing.description)}</div>
          <button class="btn btn-small" data-copy="description">📋 Copy</button></div>
        <div class="row">
          <a class="btn btn-chrome btn-small" href="${esc(listing.sell_url)}" target="_blank" rel="noopener">🌐 Open ${esc(listing.name)}</a>
          <button class="btn btn-chrome btn-small" data-folder>📁 Show the photos</button>
          ${assist ? `<button class="btn btn-chrome btn-small" data-assist>🪄 Fill it in for me</button>` : ""}
          <span class="spacer"></span>
          ${status === "listed" ? "" : `<button class="btn btn-green btn-small" data-listed>✅ I've listed it</button>`}
        </div>`}
      <script type="application/json" class="listing-data">${JSON.stringify(listing).replace(/</g, "\\u003c")}</script>
    </div>`;
}

function bindHelpers(id) {
  $$(".helper-card").forEach((card) => {
    const listing = JSON.parse($(".listing-data", card).textContent);
    $$("[data-copy]", card).forEach((b) => b.addEventListener("click", () => {
      const what = b.dataset.copy;
      copyText(what === "price" ? String(listing.price) : listing[what], what);
    }));
    const folder = $("[data-folder]", card);
    if (folder) folder.addEventListener("click", async () => {
      const res = await api(`/api/records/${id}/open-folder`, { method: "POST" });
      toast(res.ok ? "I've opened the photos folder. Drag the photos into the website." : `Photos are in: ${res.folder}`);
    });
    const assist = $("[data-assist]", card);
    if (assist) assist.addEventListener("click", async () => {
      assist.disabled = true;
      toast(`Opening ${listing.name} in a new window…`);
      try {
        const res = await api(`/api/records/${id}/assist/${listing.platform}`, { method: "POST" });
        toast(res.message, !res.ok);
      } catch (e) { toast(e.message, true); }
      assist.disabled = false;
    });
    const listed = $("[data-listed]", card);
    if (listed) listed.addEventListener("click", () => markListed(id, listing));
  });
}

function markListed(id, listing) {
  const box = openModal(`
    <h2>🎉 Well done!</h2>
    <p>If you like, paste the web address of your ${esc(listing.name)} listing here so you can find it again. (You can leave this empty.)</p>
    <input type="text" id="linkInput" placeholder="https://…">
    <div class="row" style="margin-top:20px">
      <button class="btn btn-green" id="saveListed">Save</button>
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
    </div>`);
  $("#saveListed", box).addEventListener("click", async () => {
    const link = $("#linkInput", box).value.trim();
    await api(`/api/records/${id}/platform-status`, { method: "POST", body: { platform: listing.platform, status: "listed", link: link || null } });
    closeModal();
    toast(`Marked as for sale on ${listing.name}.`);
    const card = $(`.helper-card[data-platform="${listing.platform}"]`);
    if (card) {
      card.classList.add("done");
      const badge = $("h3 .badge", card);
      badge.className = "badge for_sale"; badge.textContent = STATUS_WORDS.listed;
      const btn = $("[data-listed]", card); if (btn) btn.remove();
    }
  });
}

// ------------------------------------------------------------------ RECORD PAGE
async function renderRecord(id) {
  const rec = await api(`/api/records/${id}`);
  const platforms = await getPlatforms();
  const row = (label, value) => value ? `<tr><th>${label}</th><td>${esc(value)}</td></tr>` : "";
  const condWord = (code) => (CONDITIONS.find((c) => c[0] === code) || [code, code])[1];
  const active = platforms.filter((p) => rec[`${p.id}_status`] !== "not_listed");

  app.innerHTML = `
    <div class="row" style="margin-bottom:18px"><a class="btn btn-chrome btn-small" href="#/">⬅ Back to all my records</a></div>
    <div class="grid-2">
      <div class="panel">
        <div class="photos-big">${SLOTS.map((s) => rec.images[s.key]
          ? `<button data-photo="${esc(rec.images[s.key])}" title="Click to make bigger"><img src="${esc(rec.images[s.key])}" alt="${s.label}"></button>`
          : `<button disabled><span class="none">No ${s.label.toLowerCase()}</span></button>`).join("")}
          ${(rec.extras || []).map((e) => `<button data-photo="${esc(e.url)}" title="Click to make bigger"><img src="${esc(e.url)}" alt="${esc(e.label)}"><span class="cap">${esc(e.label)}</span></button>`).join("")}</div>
        <div class="row" style="margin-top:16px"><a class="btn btn-chrome btn-small" href="#/record/${id}/photos">📷 Retake photos</a></div>
      </div>
      <div class="panel">
        ${rec.state === "sold" ? `<div class="sold-banner">🎉 SOLD for ${money(rec.sold_price)}${rec.sold_platform ? ` on ${esc(platformName(rec.sold_platform))}` : ""}</div>` : ""}
        <h1>${esc(rec.artist || "Unknown artist")}</h1>
        <h2 style="font-style:italic;font-weight:400">${esc(rec.album_title || "Untitled")}</h2>
        <table class="facts">
          ${row("Pressed in", rec.year_pressed)}
          ${row("Made in", rec.pressing_location)}
          ${row("First released", rec.original_year !== rec.year_pressed ? rec.original_year : "")}
          ${row("Label", rec.label)}
          ${row("Catalogue number", rec.catalog_number)}
          <tr><th>Owners</th><td>${rec.is_first_owner ? "Just me - I bought it new" : `${rec.number_of_owners} owners`}</td></tr>
          ${rec.disc_count > 1 ? `<tr><th>Records in cover</th><td>${rec.disc_count} (a ${rec.disc_count}-record set)</td></tr>` : ""}
          <tr><th>Condition</th><td>Record: ${esc(condWord(rec.condition_media))} · Cover: ${esc(condWord(rec.condition_sleeve))}</td></tr>
          ${row("The record", [SCRATCH_W[rec.media_scratches], PLAY_W[rec.media_play]].filter(Boolean).join(", "))}
          ${row("The cover", [CREASE_W[rec.cover_creases], ...(rec.cover_issues || []).map((i) => ISSUE_W[i])].filter(Boolean).join(", "))}
          <tr><th>Suggested price</th><td style="font-size:1.5rem">${money(rec.suggested_price)}</td></tr>
        </table>
        ${active.length ? `<h3>Where it's listed</h3><ul class="status-list">${active.map((p) => {
          const link = (rec.listing_links || {})[p.id];
          return `<li><span class="nm">${esc(p.name)}</span><span class="badge ${rec[`${p.id}_status`] === "listed" ? "for_sale" : "ready"}">${STATUS_WORDS[rec[`${p.id}_status`]]}</span>
            ${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">Open ↗</a>` : ""}
            <span class="spacer"></span>
            ${["ready", "draft", "listed"].includes(rec[`${p.id}_status`]) ? `<button class="btn btn-small btn-chrome" data-helper="${p.id}">Show listing</button>` : ""}</li>`;
        }).join("")}</ul>` : ""}
        <div class="action-grid">
          ${rec.state === "sold"
            ? `<button class="btn btn-chrome" id="unsold">↩ Not sold after all</button>`
            : `<button class="btn btn-red btn-huge" id="sold">💰 It sold!</button>
               <a class="btn btn-green" href="#/record/${id}/sell">🛒 Sell it</a>`}
          <a class="btn" href="#/record/${id}/details">✏️ Change details</a>
          <button class="btn btn-chrome" id="reprice">🔄 Check price again</button>
        </div>
        <div id="helper"></div>
        <details class="more"><summary>Remove this record</summary>
          <button class="btn btn-red btn-small" id="delete">🗑 Delete this record</button></details>
      </div>
    </div>`;

  $$("[data-photo]").forEach((b) => b.addEventListener("click", () => showPhoto(b.dataset.photo)));
  $$("[data-helper]").forEach((b) => b.addEventListener("click", async () => {
    const listing = await api(`/api/records/${id}/listing/${b.dataset.helper}`);
    $("#helper").innerHTML = helperCardHTML(listing);
    bindHelpers(id);
    $("#helper").scrollIntoView({ behavior: "smooth" });
  }));
  $("#reprice").addEventListener("click", () => { flags.value.add(id); location.hash = `#/record/${id}/price`; });
  if ($("#sold")) $("#sold").addEventListener("click", () => soldDialog(rec, platforms));
  if ($("#unsold")) $("#unsold").addEventListener("click", async () => {
    if (await confirmBox("Mark this record as NOT sold?", "Yes, it's not sold")) {
      await api(`/api/records/${id}/unsold`, { method: "POST" }); route();
    }
  });
  $("#delete").addEventListener("click", async () => {
    if (await confirmBox("Delete this record and its photos for good?", "Yes, delete it", true)) {
      await api(`/api/records/${id}`, { method: "DELETE" });
      toast("Record deleted.");
      location.hash = "#/";
    }
  });
}

function soldDialog(rec, platforms) {
  const listedFirst = [...platforms].sort((a, b) => (rec[`${b.id}_status`] === "listed") - (rec[`${a.id}_status`] === "listed"));
  let where = listedFirst.find((p) => rec[`${p.id}_status`] === "listed")?.id || "";
  const box = openModal(`
    <h2>💰 Congratulations!</h2>
    <div class="field"><label for="soldPrice">How much did it sell for? (${esc("NZ dollars")})</label>
      <input type="number" id="soldPrice" min="0" step="1" value="${rec.suggested_price ?? ""}" style="font-size:2rem;font-weight:900"></div>
    <div class="field"><span class="label">Where did it sell?</span>
      <div class="choices" id="soldWhere">${listedFirst.map((p) => `<button type="button" class="choice" data-p="${p.id}" aria-pressed="${where === p.id}">${esc(p.name)}</button>`).join("")}
        <button type="button" class="choice" data-p="" aria-pressed="${where === ""}">Somewhere else</button></div></div>
    <div class="row"><button class="btn btn-green btn-huge" id="saveSold">Save</button><button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
  $("#soldWhere", box).addEventListener("click", (e) => {
    const b = e.target.closest(".choice"); if (!b) return;
    where = b.dataset.p;
    $$(".choice", box).forEach((x) => x.setAttribute("aria-pressed", x === b));
  });
  $("#saveSold", box).addEventListener("click", async () => {
    const price = Number($("#soldPrice", box).value);
    if (!(price >= 0) || $("#soldPrice", box).value === "") { toast("Please type the price it sold for.", true); return; }
    const res = await api(`/api/records/${rec.id}/sold`, { method: "POST", body: { price, platform: where } });
    if (res.take_down.length) {
      openModal(`<h2>Nearly done!</h2>
        <p style="font-size:1.15rem">Remember to take the record off these other sites so nobody else buys it:</p>
        <ul style="font-size:1.2rem">${res.take_down.map((t) => `<li><b>${esc(t.name)}</b> ${t.link ? `<a href="${esc(t.link)}" target="_blank" rel="noopener">open listing ↗</a>` : ""}</li>`).join("")}</ul>
        <button class="btn btn-green" onclick="closeModal();route()">OK, I'll do that</button>`);
    } else {
      closeModal(); toast("Marked as sold. Nice one!"); route();
    }
    refreshStats();
  });
}

// ------------------------------------------------------------------ SETTINGS
const SETTINGS_SECTIONS = [
  ["About you", "These words are used in every listing.", [
    ["SELLER_NAME", "Your first name"], ["SELLER_LOCATION", "Where you post from (e.g. Tauranga, New Zealand)"],
    ["HOME_CURRENCY", "Your currency (NZD)"], ["SHIPPING_NOTE", "Postage note added to listings"]]],
  ["AI helper (OpenRouter)", "Reads the photos and researches prices on the internet. Create a key at openrouter.ai/keys and add a few dollars of credit.", [
    ["OPENROUTER_API_KEY", "OpenRouter API key"], ["OPENROUTER_MODEL", "AI model (must support images)"], ["AI_WEB_SEARCH", "Search the web (true/false)"]]],
  ["Discogs", "Free token from discogs.com/settings/developers. Finds exact pressings, prices, and posts Discogs listings.", [
    ["DISCOGS_API_TOKEN", "Discogs personal token"], ["DISCOGS_LISTING_STATUS", "New listings start as (Draft or For Sale)"]]],
  ["TradeMe (optional)", "Needs an approved TradeMe API application. Without it, TradeMe uses the copy & paste helper.", [
    ["TRADEME_CONSUMER_KEY", "Consumer key"], ["TRADEME_CONSUMER_SECRET", "Consumer secret"],
    ["TRADEME_OAUTH_TOKEN", "OAuth token"], ["TRADEME_OAUTH_TOKEN_SECRET", "OAuth token secret"],
    ["TRADEME_SANDBOX", "Use the TradeMe test site (true/false)"], ["TRADEME_CATEGORY", "Vinyl category number"], ["TRADEME_DURATION_DAYS", "Listing length in days"]]],
  ["eBay (optional)", "Needs an eBay developer account, a user token and business policies. Without it, eBay uses the copy & paste helper.", [
    ["EBAY_OAUTH_TOKEN", "User access token"], ["EBAY_SANDBOX", "Use the eBay test site (true/false)"],
    ["EBAY_MARKETPLACE_ID", "Marketplace (EBAY_US, EBAY_GB, EBAY_AU)"], ["EBAY_CURRENCY", "Currency (USD, GBP, AUD)"],
    ["EBAY_CATEGORY_ID", "Category (176985 = Vinyl Records)"], ["EBAY_FULFILLMENT_POLICY_ID", "Shipping policy ID"],
    ["EBAY_PAYMENT_POLICY_ID", "Payment policy ID"], ["EBAY_RETURN_POLICY_ID", "Return policy ID"], ["EBAY_LOCATION_KEY", "Inventory location key"]]],
  ["Popsike (past auction prices)", "Popsike archives what records really sold for on eBay. Log in once with the buttons below, then prices are read automatically.", [
    ["POPSIKE_ENABLED", "Use Popsike prices (true/false)"],
    ["POPSIKE_SEARCH_URL", "Popsike search address ({query} becomes the artist and album)"]]],
  ["Selling sites", "Which sites appear when selling (comma separated: trademe, discogs, ebay, facebook, gumtree).", [
    ["ENABLED_PLATFORMS", "Sites to use"]]],
  ["Backup", "Leave the folder empty to find Google Drive automatically.", [
    ["BACKUP_FOLDER", "Backup folder"], ["BACKUP_EVERY_HOURS", "Back up at least every … hours"]]],
];

async function renderSettings() {
  const [{ settings, secret_keys: secrets }, backupInfo] = await Promise.all([api("/api/settings"), api("/api/backup")]);
  app.innerHTML = `
    <div class="row" style="margin-bottom:18px"><a class="btn btn-chrome btn-small" href="#/">⬅ Back to my records</a></div>
    <form class="panel" id="settingsForm" autocomplete="off">
      <h1>⚙️ Settings</h1>
      <p class="muted">This page is for setting things up. Once it's done you won't need to come back here.</p>
      <div class="settings-section"><h2>Camera</h2>
        <div class="field"><label for="camSel">Which camera to use</label><select id="camSel"><option value="">Default camera</option></select></div></div>
      <div class="settings-section"><h2>Popsike login</h2>
        <p id="popsikeState" class="muted">Checking…</p>
        <div class="row">
          <button type="button" class="btn btn-small" id="psLogin">🔑 Log in to Popsike</button>
          <button type="button" class="btn btn-green btn-small" id="psDone">✅ I've logged in</button>
          <button type="button" class="btn btn-chrome btn-small" id="psTest">🧪 Test Popsike</button>
        </div>
        <p class="muted" style="margin-top:10px">Press <b>Log in</b>, then use "Log in with Google" on the Popsike window that opens (your Google password is only ever typed into Google's own page). When you're in, close that window and press <b>I've logged in</b>.</p></div>
      <div class="settings-section"><h2>Activity</h2>
        <a class="btn btn-chrome" href="#/logs">📜 What has the app been doing?</a></div>
      <div class="settings-section"><h2>Backup status</h2>
        <p>${backupInfo.folder ? `Backing up to <b>${esc(backupInfo.folder)}</b>` : "⚠️ Google Drive for Desktop wasn't found on this computer."}<br>
        Last backup: <b>${esc(backupInfo.last_backup || "never")}</b> ${backupInfo.last_result ? `— ${esc(backupInfo.last_result)}` : ""}</p></div>
      ${SETTINGS_SECTIONS.map(([title, blurb, fields]) => `
        <div class="settings-section"><h2>${esc(title)}</h2><p>${esc(blurb)}</p>
          <div class="form-grid">${fields.map(([key, label]) => `
            <div class="field"><label for="s_${key}">${esc(label)}</label>
              <input type="${secrets.includes(key) ? "password" : "text"}" id="s_${key}" name="${key}" value="${esc(settings[key])}"></div>`).join("")}
          </div></div>`).join("")}
      <button class="btn btn-huge btn-green" type="submit">Save settings</button>
    </form>`;

  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    const sel = $("#camSel");
    devices.forEach((d, i) => sel.insertAdjacentHTML("beforeend", `<option value="${esc(d.deviceId)}">${esc(d.label || `Camera ${i + 1}`)}</option>`));
    sel.value = store.get("pv.camera", "");
    sel.addEventListener("change", () => { store.set("pv.camera", sel.value); toast("Camera choice saved."); });
  } catch (_) { /* no camera API */ }

  const psState = async () => {
    try {
      const s = await api("/api/popsike/status");
      $("#popsikeState").textContent = !s.browser_found ? "⚠️ Google Chrome (or Microsoft Edge) wasn't found, so the Popsike login can't be saved."
        : s.connected ? "✅ Logged in to Popsike (press Test Popsike to check it still works)." : "Not logged in yet.";
    } catch (_) { $("#popsikeState").textContent = ""; }
  };
  psState();
  $("#psLogin").addEventListener("click", async () => { const r = await api("/api/popsike/connect", { method: "POST" }); toast(r.message, !r.ok); });
  $("#psDone").addEventListener("click", async () => { const r = await api("/api/popsike/done", { method: "POST" }); toast(r.message, !r.ok); psState(); });
  $("#psTest").addEventListener("click", async () => {
    const b = $("#psTest"); b.disabled = true; b.textContent = "Testing… (up to a minute)";
    try { const r = await api("/api/popsike/test", { method: "POST" }); toast(r.message, !r.ok); } catch (e) { toast(e.message, true); }
    b.disabled = false; b.textContent = "🧪 Test Popsike";
  });

  // Only send fields that were actually edited, so masked secrets are never overwritten.
  const changed = new Set();
  $$("#settingsForm input[name]").forEach((el) => el.addEventListener("input", () => changed.add(el.name)));
  $("#settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {};
    changed.forEach((name) => { body[name] = $(`#s_${name}`).value; });
    await api("/api/settings", { method: "PUT", body });
    store.set("pv.name", $("#s_SELLER_NAME").value || "Pete");
    platformsCache = null;
    toast("Settings saved.");
    renderSettings();
    refreshBackup();
  });
}

// ------------------------------------------------------------------ ACTIVITY LOG
function ago(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 2) return "just now";
  if (mins < 90) return `${mins} minutes ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs} hours ago`;
  return `${Math.round(hrs / 24)} days ago`;
}
const niceTime = (iso) => new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function backupsHTML(log) {
  const last = log.last_ok;
  const stale = !last || Date.now() - new Date(last.at).getTime() > 24 * 3600 * 1000;
  const banner = last
    ? `<div class="backup-banner ${stale ? "warn" : "good"}">${stale ? "⚠️" : "✅"} Last successful backup: <b>${esc(niceTime(last.at))}</b> (${ago(last.at)})${stale ? " - it's been over a day. Press Back up now." : ""}</div>`
    : `<div class="backup-banner warn">⚠️ There hasn't been a successful backup yet. Press <b>Back up now</b>.</div>`;
  return `<div class="panel" id="backups" style="margin-bottom:22px">
    <h1>💾 Backups to Google Drive</h1>
    ${banner}
    <div class="row" style="margin:14px 0">
      <button class="btn btn-green btn-small" id="backupNow">💾 Back up now</button>
      <span class="muted">Saving to: ${esc(log.status.folder || "(Google Drive not found)")}</span>
    </div>
    ${log.entries.length ? `<table class="backup-table"><thead><tr><th>When</th><th></th><th>What happened</th><th>How</th></tr></thead><tbody>
      ${log.entries.map((e) => `<tr class="${e.ok ? "" : "bad"}"><td>${esc(niceTime(e.at))}<br><span class="muted">${ago(e.at)}</span></td>
        <td>${e.ok ? "✅" : "❌"}</td><td>${esc(e.message)}</td><td>${esc(e.kind)}</td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">No backups recorded yet.</p>`}
  </div>`;
}

async function renderLogs() {
  const [{ events }, backupLog] = await Promise.all([api("/api/activity"), api("/api/backup-log")]);
  app.innerHTML = `
    <div class="row" style="margin-bottom:18px"><a class="btn btn-chrome btn-small" href="#/settings">⬅ Back to settings</a>
      <button class="btn btn-small" id="refreshLog">🔄 Refresh</button>
      <button class="btn btn-green btn-small" id="testKeys">🔌 Test my keys</button></div>
    <div id="testResult"></div>
    ${backupsHTML(backupLog)}
    <div class="panel"><h1>What has the app been doing?</h1>
      <p class="muted">Newest first. Every time the app asks Discogs, OpenRouter or eBay something, it shows up here. Red lines are problems. (Also saved in the <b>logs</b> folder as activity.log.)</p>
      ${events.length ? events.map((e) => `
        <div class="helper-card ${e.ok ? "done" : ""}" style="${e.ok ? "" : "border-color:var(--red)"}">
          <b>${e.ok ? "✅" : "❌"} ${esc(e.source)}</b> <span class="muted">${esc(e.time)}</span><br>${esc(e.what)}
          ${e.detail ? `<pre style="white-space:pre-wrap;margin:8px 0 0;font-size:.85rem;color:var(--text-dim)">${esc(e.detail)}</pre>` : ""}
        </div>`).join("") : "<p>Nothing yet. Look up a record and come back.</p>"}
    </div>`;
  $("#refreshLog").addEventListener("click", renderLogs);
  $("#backupNow").addEventListener("click", async () => {
    const btn = $("#backupNow");
    btn.disabled = true; btn.textContent = "Backing up…";
    try { const r = await api("/api/backup", { method: "POST" }); toast(r.message, !r.ok); } catch (e) { toast(e.message, true); }
    renderLogs();
  });
  $("#testKeys").addEventListener("click", async () => {
    const btn = $("#testKeys");
    btn.disabled = true; btn.textContent = "Testing…";
    let html;
    try {
      const r = await api("/api/test-connections", { method: "POST" });
      html = [["Discogs", r.discogs], ["OpenRouter", r.openrouter]].map(([n, x]) =>
        `<p style="font-size:1.2rem"><b>${x.ok ? "✅" : "❌"} ${n}:</b> ${esc(x.message)}</p>`).join("");
    } catch (e) {
      html = `<p style="font-size:1.2rem"><b>❌ The test couldn't run:</b> ${esc(e.message)}<br>
        <span class="muted">If it says "Not Found", the app is still running an older version. Run Stop_PetesVinyl.bat and start it again.</span></p>`;
    }
    await renderLogs();
    $("#testResult").innerHTML = `<div class="panel" style="margin-bottom:18px">${html}</div>`;
  });
}

// ------------------------------------------------------------------ start
function showRestartBanner() {
  if ($("#restartBanner")) return;
  document.body.insertAdjacentHTML("afterbegin", `<div id="restartBanner" class="restart-banner">
    🔄 <b>Pete's Vinyl has been updated and needs a restart.</b> Close this window, then double-click
    <b>Pete's Vinyl</b> on the desktop. (If this message comes back, run <b>Stop_PetesVinyl.bat</b> first.)</div>`);
}
async function checkVersion() {
  try {
    const v = await api("/api/version");
    if (v.stale) showRestartBanner();
  } catch (e) {
    if (!(e instanceof TypeError)) showRestartBanner();   // "Not Found": this server predates the update
  }
}

(async function start() {
  checkVersion();
  try {
    const s = await api("/api/settings");
    store.set("pv.name", s.settings.SELLER_NAME || "Pete");
  } catch (_) { /* first run */ }
  refreshStats();
  refreshBackup();
  route();
})();
