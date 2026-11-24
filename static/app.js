const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n) => (n == null ? "—" : "$" + (n >= 100 ? Math.round(n).toLocaleString() : n.toFixed(2).replace(/\.00$/, "")));
const DAY = 86400000;
const PRIORITY = { 1: "Must have", 2: "Want", 3: "Maybe" };
const PAGE = 24;

let S = null;
const ui = { cat: "", shown: PAGE, open: new Set(), allWishes: false, seed: Math.random() };

const localDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const today = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
const fmtDay = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
const daysBetween = (a, b) => Math.round((b - a) / DAY);
const inDays = (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`);
function ago(iso) {
  const m = Math.max(0, (Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${Math.round(m)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  if (m < 45 * 1440) return `${Math.round(m / 1440)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body && JSON.stringify(opts.body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

async function load() {
  S = await api("/api/state");
  render();
  const btn = $("#refreshBtn");
  btn.classList.toggle("spinning", S.meta.refreshing);
  btn.querySelector("span").textContent = S.meta.refreshing ? "Refreshing…" : "Refresh";
  if (S.meta.refreshing) setTimeout(load, 2500);
}

function render() {
  if (S.needs_setup) return openSetup(false);
  if (!setupOpen()) $("#app").classList.remove("hidden");
  $("#appTitle").textContent = document.title = S.profile.title || "Deal Radar";
  renderCountdown();
  renderTimeline();
  renderWishlist();
  renderFeed();
  const m = S.meta;
  const failed = Object.entries(m.sources || {}).filter(([, v]) => !v.ok);
  $("#updated").innerHTML = (m.last_refresh ? `Updated ${ago(m.last_refresh)}` : "Not refreshed yet") +
    (failed.length ? ` · <span title="${esc(failed.map(([k, v]) => `${k}: ${v.error}`).join("\n"))}">${failed.length} store${failed.length > 1 ? "s" : ""} didn't load</span>` : "");
}

/* ---------- events helpers ---------- */
function eventSpan(e) {
  const start = localDate(e.start);
  // an event without an end date is drawn as running for a week
  const end = e.end ? localDate(e.end) : new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7);
  return { start, end, open: !e.end };
}
function eventStatus(e) {
  const t = today();
  const { start, end } = eventSpan(e);
  if (t < start) return { kind: "upcoming", days: daysBetween(t, start) };
  if (t <= end) return { kind: "live", days: daysBetween(t, end) };
  return { kind: "past" };
}

/* ---------- countdown ---------- */
function meterPct(x) {
  if (!x.now_price || !x.target_price) return 0;
  return Math.min(100, Math.round((x.target_price / x.now_price) * 100));
}
function renderCountdown() {
  const c = S.profile.countdown;
  const days = c ? daysBetween(today(), localDate(c.date)) : -1;
  $("#countdown").textContent = days > 1 ? `${days} days to ${c.label}` : days === 1 ? `${c.label} is tomorrow` :
    days === 0 ? `It's ${c.label} ♡` : "";
}

/* ---------- calendar ---------- */
function renderTimeline() {
  const evs = S.events.map((e) => ({ e, st: eventStatus(e), ...eventSpan(e) })).filter((x) => x.st.kind !== "past");
  evs.sort((a, b) => (b.st.kind === "live") - (a.st.kind === "live") || a.start - b.start);
  $("#timeline").innerHTML = evs.map(({ e, st, start, end, open }) => {
    const key = e.retailer === "Everyone";
    const range = open ? `from ${fmtDay(start)}` : +start === +end ? fmtDay(start) : `${fmtDay(start)} – ${fmtDay(end)}`;
    const when = st.kind === "live" ? (open ? range : `ends ${inDays(st.days)}`) : `${range} · ${inDays(st.days)}`;
    const title = [e.note, e.status === "mine" ? "Added by you · double-click to delete" : "", e.url ? "Click to open the sale page" : ""].filter(Boolean).join("\n");
    return `
      <div class="ticket ${key ? "key" : ""} ${st.kind === "live" ? "live" : ""}" data-ev="${e.id}" title="${esc(title)}">
        <div class="tdate"><b>${start.getDate()}</b><span>${start.toLocaleDateString("en-US", { month: "short" })}</span></div>
        <div class="tbody">
          <span class="tstore">${esc(e.retailer === "Everyone" ? "Everywhere" : e.retailer)}</span>
          <span class="tname">${esc(e.name)}</span>
          <span class="twhen">${when}</span>
          ${e.status === "expected" ? `<span class="tag">expected</span>` : e.status === "mine" ? `<span class="tag">added by you</span>` : ""}
        </div>
      </div>`;
  }).join("") || `<div class="empty">No sales coming up. Add one with “Add a date”.</div>`;
}
document.addEventListener("dblclick", async (ev) => {
  const el = ev.target.closest(".ticket");
  if (!el) return;
  const e = S.events.find((x) => x.id == el.dataset.ev);
  if (e.status === "mine" && confirm(`Delete "${e.name}"?`)) { await api(`/api/events/${e.id}`, { method: "DELETE" }); load(); }
});
document.addEventListener("click", (ev) => {
  const el = ev.target.closest(".ticket");
  if (!el) return;
  const e = S.events.find((x) => x.id == el.dataset.ev);
  if (e?.url) window.open(e.url, "_blank", "noopener");
});

/* ---------- wishlist ---------- */
const cleanQuery = (q) => q.replace(/\s-("[^"]*"|\S+)/g, "").replace(/"/g, "");

function renderWishlist() {
  const w = S.wishlist;
  if (!w.length) {
    $("#wishlist").innerHTML = `<div class="empty">Add something you're dreaming of ♡<br>Deal Radar looks for it everywhere and pings you when it hits your price.</div>`;
    return;
  }
  const rank = { hit: 0, sale: 1, close: 2, watching: 3, waiting: 4 };
  const sorted = [...w].sort((a, b) => rank[a.status] - rank[b.status] || meterPct(b) - meterPct(a));
  const visible = ui.allWishes ? sorted : sorted.slice(0, 8);
  const label = { hit: "dream price ♡", sale: "on sale", close: "so close", watching: "watching", waiting: "looking…" };
  $("#wishlist").innerHTML = visible.map((x) => {
    const b = x.best_now;
    const open = ui.open.has(x.id);
    const storeSale = x.page_price && x.page_regular && x.page_price < x.page_regular;
    const pagePrice = x.page_price ? `<b>${usd(x.page_price)}</b>${storeSale ? ` <s>${usd(x.page_regular)}</s> <span class="save">${Math.round(100 * (1 - x.page_price / x.page_regular))}% off</span>` : ""}` : esc(x.page_status || "not checked yet");
    const pageLine = x.product_url ? `<div class="page-status">At the store: ${pagePrice} · <a href="${esc(x.product_url)}" target="_blank" rel="noopener">open</a></div>` : "";
    const pct = meterPct(x);
    const sub = !x.now_price ? "No deals spotted yet, still looking" : !x.target_price ? "Tap the price to set your dream price" :
      x.status === "hit" ? "It's at your price, go go go!" : `${usd(x.now_price - x.target_price)} to go`;
    return `
      <div class="wcard ${x.status} ${open ? "open" : ""}" data-toggle="${x.id}">
        <div class="top">
          <div><h3>${esc(cleanQuery(x.query))}</h3>${x.note ? `<div class="note">${esc(x.note)}</div>` : ""}</div>
          <span class="sticker ${x.status}">${label[x.status]}</span>
        </div>
        <div class="wprices">
          <span class="now"><small>now</small>${usd(x.now_price)}</span>
          <span class="goal">dream price <b data-edit="${x.id}" title="Click to change">${x.target_price ? usd(x.target_price) : "set"}</b></span>
        </div>
        <div class="meter"><i style="width:${pct}%"></i></div>
        <div class="wsub">${sub}</div>
        ${open ? `<div class="wdetail">
          ${b ? `<a class="wbest" href="${esc(b.url)}" target="_blank" rel="noopener">Best find: <b>${usd(b.price)}</b> ${b.retailer ? `at ${esc(b.retailer)}` : ""} · ${esc(b.title.slice(0, 90))}</a>` : ""}
          ${pageLine}
          ${x.lowest ? `<div class="lastbf">Lowest this year: <b>${usd(x.lowest)}</b></div>` : ""}
          ${x.last_year ? `<div class="lastbf"><a href="${esc(x.last_year.url)}" target="_blank" rel="noopener" title="${esc(x.last_year.title)}">Same time last year: <b>${usd(x.last_year.price)}</b> on ${fmtDay(new Date(x.last_year.posted_at))}</a>${x.target_price ? "" : ` · <button class="linkish" data-target="${x.id}" data-price="${x.last_year.price}">make it my dream price</button>`}</div>` : ""}
          ${x.matches.length ? `<ul class="wmatches">${x.matches.slice(0, 8).map((d) => `<li><a href="${esc(d.url)}" target="_blank" rel="noopener"><span class="p">${usd(d.price)}</span><span class="t">${d.used ? `<em class="used">used</em> ` : ""}${esc(d.title)}</span></a></li>`).join("")}</ul>` : ""}
          <div class="wfoot"><span>${PRIORITY[x.priority] || ""}</span><button class="linkish" data-del="${x.id}">Remove</button></div>
        </div>` : ""}
      </div>`;
  }).join("") + (w.length > 8 ? `<button class="btn soft small more" data-allwishes>${ui.allWishes ? "Show fewer" : `Show all ${w.length} wishes`}</button>` : "");
}

$("#wishlist").addEventListener("click", async (ev) => {
  const t = ev.target;
  if ("allwishes" in t.dataset) { ui.allWishes = !ui.allWishes; return renderWishlist(); }
  if (t.dataset.target) { await api(`/api/wishlist/${t.dataset.target}`, { method: "PUT", body: { target_price: t.dataset.price } }); return load(); }
  if (t.dataset.del && confirm("Remove from your wishlist?")) { await api(`/api/wishlist/${t.dataset.del}`, { method: "DELETE" }); return load(); }
  if (t.dataset.edit) {
    const v = prompt("Dream price in $ (blank to clear):", S.wishlist.find((x) => x.id == t.dataset.edit).target_price ?? "");
    if (v !== null) { await api(`/api/wishlist/${t.dataset.edit}`, { method: "PUT", body: { target_price: v } }); load(); }
    return;
  }
  // anywhere else on the card (but not a link or inside the details) opens/closes it
  const card = t.closest(".wcard");
  if (card && !t.closest("a, button, .wdetail")) { const id = +card.dataset.toggle; ui.open.has(id) ? ui.open.delete(id) : ui.open.add(id); renderWishlist(); }
});

$("#wishForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  try {
    await api("/api/wishlist", { method: "POST", body: Object.fromEntries(f) });
    ev.target.reset();
    ev.target.classList.add("hidden");
    load();
  } catch (e) { alert(e.message); }
});

/* ---------- feed ---------- */
function filteredDeals() {
  const q = $("#search").value.trim().toLowerCase();
  const store = $("#source").value;
  const sale = $("#saleOnly").checked;
  let list = S.deals.filter((d) =>
    (!ui.cat || d.category === ui.cat) && (!store || storeOf(d) === store) && (!sale || d.orig_price) &&
    (!q || q.split(/\s+/).every((w) => `${d.title} ${d.retailer || ""} ${d.category}`.toLowerCase().includes(w))));
  const sorters = {
    score: (a, b) => b.score - a.score,
    discount: (a, b) => (b.discount_pct || 0) - (a.discount_pct || 0),
    new: (a, b) => new Date(b.posted_at) - new Date(a.posted_at),
    shuffle: (a, b) => shuffleKey(a) - shuffleKey(b),
    price: (a, b) => (a.price ?? 1e9) - (b.price ?? 1e9),
  };
  return $("#sort").value === "score" ? mixStores(list) : list.sort(sorters[$("#sort").value]);
}

// Favourite brands first (their order in the profile), then the rest by their best item.
function storeRank(store) {
  const i = S.profile.brands.findIndex((b) => b.toLowerCase() === store.toLowerCase());
  return i < 0 ? 999 : i;
}
// "Picked for me": take turns between stores so one big sale can't fill the whole page.
function mixStores(list) {
  const groups = new Map();
  [...list].sort((a, b) => b.score - a.score).forEach((d) => {
    const k = storeOf(d);
    groups.has(k) ? groups.get(k).push(d) : groups.set(k, [d]);
  });
  const order = [...groups.values()].sort((a, b) => storeRank(storeOf(a[0])) - storeRank(storeOf(b[0])) || b[0].score - a[0].score);
  const out = [];
  for (let i = 0; out.length < list.length; i++) order.forEach((g) => g[i] && out.push(g[i]));
  return out;
}

const storeOf = (d) => d.retailer || d.source;
// a fixed random order per visit, so "Surprise me" doesn't reshuffle every time the page refreshes
const shuffleKey = (d) => { const x = Math.sin(d.id * 12.9898 + ui.seed * 1000) * 43758.5453; return x - Math.floor(x); };

const noImg = `onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'noimg',textContent:'✿'}))"`;

function renderFeed() {
  const srcSel = $("#source");
  const shops = [...new Set(S.deals.filter((d) => d.kind === "product").map(storeOf))].sort((a, b) => storeRank(a) - storeRank(b) || a.localeCompare(b));
  const others = [...new Set(S.deals.filter((d) => d.kind !== "product").map(storeOf))].filter((x) => !shops.includes(x)).sort();
  const opts = `<option value="">All stores</option>` + shops.map((x) => `<option>${esc(x)}</option>`).join("") +
    (others.length ? `<optgroup label="Deals at other stores">${others.map((x) => `<option>${esc(x)}</option>`).join("")}</optgroup>` : "");
  if (srcSel.dataset.opts !== opts) {
    const cur = srcSel.value;
    srcSel.innerHTML = opts;
    srcSel.dataset.opts = opts;
    srcSel.value = cur;
  }
  const order = ["Wishlist", ...S.profile.interests.map((i) => i.name), "Your brands", "Store sales"];
  const cats = [...new Set(S.deals.map((d) => d.category))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const from = shops.length ? `Sale and new-in picks from ${shops.slice(0, 3).map(esc).join(", ")}${shops.length > 3 ? ` and ${shops.length - 3} more` : ""}` : "Deals from deal-site feeds";
  $("#forYou").innerHTML = `${from}, updated every ${S.meta.refresh_every_min} minutes · <button class="linkish" data-open-profile>edit preferences</button>`;
  $("#cats").innerHTML = [`<button class="chip ${!ui.cat ? "on" : ""}" data-cat="">Everything</button>`]
    .concat(cats.map((c) => `<button class="chip ${ui.cat === c ? "on" : ""}" data-cat="${esc(c)}">${esc(c)}</button>`)).join("");

  renderSpotlight();
  const list = filteredDeals();
  $("#deals").innerHTML = list.slice(0, ui.shown).map((d) => {
    const off = d.discount_pct ? Math.round(d.discount_pct) : null;
    const isNew = d.kind !== "product" && Date.now() - new Date(d.posted_at) < DAY;
    return `
      <a class="deal ${d.kind === "product" ? "product" : ""}" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.summary)}">
        <div class="img">
          ${d.image ? `<img loading="lazy" src="${esc(d.image)}" alt="" ${noImg}>` : `<span class="noimg">✿</span>`}
          ${off ? `<span class="off">${off}% off</span>` : ""}
          ${isNew ? `<span class="new">just in</span>` : ""}
        </div>
        <div class="body">
          ${d.retailer ? `<span class="r">${esc(d.retailer)}</span>` : ""}
          <div class="title">${esc(d.title)}</div>
          <div class="price">${d.price != null ? `<b>${usd(d.price)}</b>` : ""}${d.orig_price ? `<s>${usd(d.orig_price)}</s>` : ""}</div>
          ${d.wish_ids.length || d.coupon ? `<div class="tags">${d.wish_ids.length ? `<span class="tagpill wish">♡ on your wishlist</span>` : ""}${d.coupon ? `<span class="tagpill">code ${esc(d.coupon)}</span>` : ""}</div>` : ""}
        </div>
      </a>`;
  }).join("") + (list.length > ui.shown ? `<button class="btn soft small more" id="moreBtn">Show more</button>` : "")
    || `<div class="empty">Nothing matches that yet. Try another search ♡</div>`;
}

function renderSpotlight() {
  const focus = S.profile.interests.filter((i) => i.focus).map((i) => i.name);
  $("#spotlight").innerHTML = focus.map((name) => {
    const top = S.deals.filter((d) => d.category === name)
      .sort((a, b) => (b.discount_pct || 0) - (a.discount_pct || 0) || (a.unit_price ?? 1e9) - (b.unit_price ?? 1e9) || b.score - a.score).slice(0, 4);
    if (!top.length) return "";
    return `<div class="spot"><div class="spot-head"><b>The ${esc(name.toLowerCase())} edit</b>
      <button class="linkish" data-cat-jump="${esc(name)}">see all</button></div>
      <div class="spot-row">${top.map((d) => `
        <a class="spot-card" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.title)}">
          <span class="spot-img">${d.image ? `<img loading="lazy" src="${esc(d.image)}" alt="" ${noImg}>` : "✿"}</span>
          <span class="spot-txt"><b>${d.unit_price ? `${usd(d.unit_price)} each` : usd(d.price)}${d.discount_pct ? ` <span class="off">${Math.round(d.discount_pct)}% off</span>` : ""}</b><span class="t">${esc(d.title)}</span>${d.retailer ? `<em>${esc(d.retailer)}</em>` : ""}</span>
        </a>`).join("")}</div></div>`;
  }).join("");
}
$("#spotlight").addEventListener("click", (ev) => {
  const j = ev.target.closest("[data-cat-jump]");
  if (j) { ui.cat = j.dataset.catJump; ui.shown = PAGE; $("#sort").value = "discount"; renderFeed(); $("#cats").scrollIntoView({ behavior: "smooth", block: "start" }); }
});

$("#cats").addEventListener("click", (ev) => {
  const c = ev.target.closest(".chip");
  if (c) { ui.cat = c.dataset.cat; ui.shown = PAGE; renderFeed(); }
});
$("#deals").addEventListener("click", (ev) => {
  if (ev.target.id === "moreBtn") { ev.preventDefault(); ui.shown += PAGE; renderFeed(); }
});
["#search", "#sort", "#source", "#saleOnly"].forEach((s) => $(s).addEventListener("input", () => { ui.shown = PAGE; renderFeed(); }));

/* ---------- profile ---------- */
const modal = $("#profileModal"), pform = $("#profileForm");
const interestRow = (i = { name: "", keywords: [] }) => `
  <div class="irow"><div class="iname"><input name="iname" placeholder="Section name" value="${esc(i.name)}">
  <label class="star" title="Feature this section at the top"><input type="checkbox" name="ifocus" ${i.focus ? "checked" : ""}> ★ Featured</label></div>
  <textarea name="ikeys" rows="1" placeholder="keywords, comma-separated">${esc(i.keywords.join(", "))}</textarea>
  <button type="button" class="linkish" data-rm>Remove</button></div>`;
function openProfile() {
  const p = S.profile;
  pform.about.value = p.about || "";
  pform.brands.value = (p.brands || []).join(", ");
  pform.stores.value = (p.stores || []).join(", ");
  pform.shops.value = (p.shops || []).join(", ");
  $("#shopsHint").textContent = `leave empty to browse every store: ${Object.keys(S.setup_options.stores).join(", ")}`;
  pform.avoid.value = (p.avoid || []).join(", ");
  $("#interests").innerHTML = (p.interests || []).map(interestRow).join("");
  modal.classList.remove("hidden");
}
const split = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);
document.addEventListener("click", (ev) => {
  if (ev.target.closest("[data-open-profile]")) openProfile();
});
$("#profileBtn").addEventListener("click", openProfile);
modal.addEventListener("click", (ev) => {
  if (ev.target === modal || ev.target.closest("[data-close]")) modal.classList.add("hidden");
  if (ev.target.closest("[data-rm]")) ev.target.closest(".irow").remove();
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") modal.classList.add("hidden"); });
$("#addInterest").addEventListener("click", () => $("#interests").insertAdjacentHTML("beforeend", interestRow()));
$("#resetProfile").addEventListener("click", async () => {
  if (!confirm("Start over? Your preferences are cleared and setup opens again. The wishlist is kept.")) return;
  await api("/api/profile/reset", { method: "PUT" });
  modal.classList.add("hidden");
  load();
});
$("#rerunSetup").addEventListener("click", () => { modal.classList.add("hidden"); openSetup(true); });

/* ---------- setup ---------- */
// The setup form turns a few answers into a profile (server: profiles.build_profile). Stores are
// suggested from the department and categories until the user picks stores by hand.
const setupForm = $("#setupForm");
const setupState = { storesTouched: false };
const setupOpen = () => !$("#setup").classList.contains("hidden");
const pick = (type, name, value, label, checked, extra = "") =>
  `<label class="pick"><input type="${type}" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""}><span>${esc(label)}${extra}</span></label>`;
const checkedValues = (name) => [...setupForm.querySelectorAll(`[name="${name}"]:checked`)].map((i) => i.value);
const customRow = (c = { name: "", keywords: [] }) => `
  <div class="irow custom"><input name="cname" placeholder="Category name, e.g. Board games" value="${esc(c.name)}">
  <textarea name="ckeys" rows="1" placeholder="words to look for in deal titles, comma-separated">${esc((c.keywords || []).join(", "))}</textarea>
  <button type="button" class="linkish" data-rmc>Remove</button></div>`;

function suggestedStores() {
  const dept = checkedValues("department")[0] || "all", cats = checkedValues("cat");
  return Object.entries(S.setup_options.stores)
    .filter(([, info]) => info.sells.some((c) => cats.includes(c)) && (dept === "all" || info.for === "all" || info.for === dept))
    .map(([name]) => name);
}
function refreshSetupPicks() {
  if (!setupState.storesTouched) {
    const want = suggestedStores();
    setupForm.querySelectorAll('[name="shop"]').forEach((i) => (i.checked = want.includes(i.value)));
  }
  const names = checkedValues("cat").concat([...setupForm.querySelectorAll("[name=cname]")].map((i) => i.value.trim()).filter(Boolean));
  const sel = $("#setupFeatured"), cur = sel.value;
  sel.innerHTML = `<option value="">None</option>` + names.map((n) => `<option>${esc(n)}</option>`).join("");
  sel.value = names.includes(cur) ? cur : "";
}
function fillSetup(a = {}) {
  const o = S.setup_options;
  setupForm.title.value = a.title || "";
  setupForm.about.value = a.about || "";
  setupForm.brands.value = (a.brands || []).join(", ");
  setupForm.avoid.value = (a.avoid || []).join(", ");
  setupForm.hide_common.checked = a.hide_common !== false;
  setupForm.countdown_label.value = a.countdown?.label || "";
  setupForm.countdown_date.value = a.countdown?.date || "";
  $("#setupDept").innerHTML = Object.entries(o.departments).map(([k, v]) => pick("radio", "department", k, v, (a.department || "all") === k)).join("");
  $("#setupCats").innerHTML = o.categories.map((c) => pick("checkbox", "cat", c, c, (a.categories || []).includes(c))).join("");
  $("#setupCustom").innerHTML = (a.custom || []).map(customRow).join("");
  const shops = a.shops || [];
  $("#setupStores").innerHTML = Object.entries(o.stores).map(([n, info]) =>
    pick("checkbox", "shop", n, n, shops.includes(n), `<small>${esc(info.sells.join(", "))}</small>`)).join("");
  // an answer with an explicit store list keeps it; otherwise follow the suggestions
  setupState.storesTouched = shops.length > 0;
  $("#setupSaleDates").innerHTML = `<option value="">None</option>` + o.sale_dates.map((n) => `<option>${esc(n)}</option>`).join("");
  setupForm.sale_dates.value = a.sale_dates || "";
  refreshSetupPicks();
  setupForm.featured.value = a.featured || "";
}
function openSetup(cancelable) {
  if (!setupOpen()) {
    $("#presets").innerHTML = Object.keys(S.setup_options.presets).map((n) => `<button type="button" class="btn soft small" data-preset="${esc(n)}">${esc(n)}</button>`).join("");
    fillSetup(S.profile?.setup);
  }
  $("#setupCancel").classList.toggle("hidden", !cancelable);
  $("#setup").classList.remove("hidden");
  $("#app").classList.add("hidden");
  $("#countdown").textContent = "";
  window.scrollTo(0, 0);
}
function closeSetup() {
  $("#setup").classList.add("hidden");
  $("#app").classList.remove("hidden");
}
setupForm.addEventListener("change", (ev) => {
  if (ev.target.name === "shop") setupState.storesTouched = true;
  if (["department", "cat", "cname"].includes(ev.target.name)) refreshSetupPicks();
});
setupForm.addEventListener("click", (ev) => {
  const preset = ev.target.closest("[data-preset]");
  if (preset) fillSetup(S.setup_options.presets[preset.dataset.preset]);
  if (ev.target.closest("[data-rmc]")) { ev.target.closest(".irow").remove(); refreshSetupPicks(); }
});
$("#addCustom").addEventListener("click", () => $("#setupCustom").insertAdjacentHTML("beforeend", customRow()));
$("#setupCancel").addEventListener("click", closeSetup);
setupForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const custom = [...setupForm.querySelectorAll(".irow.custom")].map((r) => ({
    name: r.querySelector("[name=cname]").value.trim(), keywords: split(r.querySelector("[name=ckeys]").value) })).filter((c) => c.name);
  const categories = checkedValues("cat");
  if (!categories.length && !custom.length) return alert("Pick at least one category, or add your own.");
  const shops = checkedValues("shop");
  const answers = {
    title: setupForm.title.value.trim(), about: setupForm.about.value.trim(),
    department: checkedValues("department")[0] || "all", categories, custom, featured: setupForm.featured.value,
    // every store ticked means "all stores", which also picks up stores added later
    shops: shops.length === Object.keys(S.setup_options.stores).length ? [] : shops,
    brands: split(setupForm.brands.value), hide_common: setupForm.hide_common.checked, avoid: split(setupForm.avoid.value),
    countdown: setupForm.countdown_date.value ? { label: setupForm.countdown_label.value.trim(), date: setupForm.countdown_date.value } : null,
    sale_dates: setupForm.sale_dates.value,
  };
  await api("/api/setup", { method: "PUT", body: answers });
  closeSetup();
  ui.cat = "";
  load();
});
pform.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const interests = [...pform.querySelectorAll(".irow")].map((r) => ({ name: r.querySelector("[name=iname]").value, keywords: split(r.querySelector("[name=ikeys]").value), focus: r.querySelector("[name=ifocus]").checked }));
  await api("/api/profile", { method: "PUT", body: { about: pform.about.value, brands: split(pform.brands.value), stores: split(pform.stores.value), shops: split(pform.shops.value), avoid: split(pform.avoid.value), interests } });
  modal.classList.add("hidden");
  ui.cat = "";
  load();
});

/* ---------- misc ---------- */
$("#refreshBtn").addEventListener("click", async () => { await api("/api/refresh", { method: "POST" }); load(); });

// theme: auto (follows the OS setting) -> light -> dark; stored in localStorage
const THEMES = { auto: ["◐", "Auto"], light: ["☀", "Light"], dark: ["☾", "Dark"] };
function setTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch (e) {}
  $("#themeBtn").innerHTML = `<span>${THEMES[t][0]}</span><span class="lbl">${THEMES[t][1]}</span>`;
}
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || "auto";
  setTheme({ auto: "light", light: "dark", dark: "auto" }[cur]);
});
setTheme(document.documentElement.dataset.theme || "auto");
$("#addWishBtn").addEventListener("click", () => { $("#wishForm").classList.toggle("hidden"); $("#wishForm").query.focus(); });
$("#addEventBtn").addEventListener("click", () => $("#eventForm").classList.toggle("hidden"));
$("#eventForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/events", { method: "POST", body: Object.fromEntries(new FormData(ev.target)) });
  ev.target.reset();
  ev.target.classList.add("hidden");
  load();
});

load();
setInterval(load, 5 * 60 * 1000);
