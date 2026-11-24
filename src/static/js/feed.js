// The deal feed: section chips, filters, featured rows and the product grid.
import { $, DAY, app, esc, usd } from "./util.js";

const PAGE = 24;  // items per "Show more"
const view = { cat: "", shown: PAGE, seed: Math.random() };
const storeOf = (d) => d.retailer || d.source;
// a fixed random order per visit, so "Surprise me" doesn't reshuffle every time the page reloads
const shuffleKey = (d) => { const x = Math.sin(d.id * 12.9898 + view.seed * 1000) * 43758.5453; return x - Math.floor(x); };
const noImg = `onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'noimg',textContent:'✿'}))"`;
const img = (d) => (d.image ? `<img loading="lazy" src="${esc(d.image)}" alt="" ${noImg}>` : "✿");

export function resetFeed() { view.cat = ""; view.shown = PAGE; }

// Favourite brands first (their order in the profile), then the rest.
function storeRank(store) {
  const i = app.S.profile.brands.findIndex((b) => b.toLowerCase() === store.toLowerCase());
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

const SORTS = {
  discount: (a, b) => (b.discount_pct || 0) - (a.discount_pct || 0),
  new: (a, b) => new Date(b.posted_at) - new Date(a.posted_at),
  shuffle: (a, b) => shuffleKey(a) - shuffleKey(b),
  price: (a, b) => (a.price ?? 1e9) - (b.price ?? 1e9),
};

function filtered() {
  const q = $("#search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const store = $("#source").value, saleOnly = $("#saleOnly").checked, sort = $("#sort").value;
  const list = app.S.deals.filter((d) =>
    (!view.cat || d.category === view.cat) && (!store || storeOf(d) === store) && (!saleOnly || d.orig_price) &&
    q.every((w) => `${d.title} ${d.retailer || ""} ${d.category}`.toLowerCase().includes(w)));
  return sort === "score" ? mixStores(list) : list.sort(SORTS[sort]);
}

function renderStoreSelect(shops) {
  const others = [...new Set(app.S.deals.filter((d) => d.kind !== "product").map(storeOf))].filter((x) => !shops.includes(x)).sort();
  const opts = `<option value="">All stores</option>` + shops.map((x) => `<option>${esc(x)}</option>`).join("") +
    (others.length ? `<optgroup label="Deals at other stores">${others.map((x) => `<option>${esc(x)}</option>`).join("")}</optgroup>` : "");
  const sel = $("#source");
  if (sel.dataset.opts !== opts) {  // rebuild only when the list changed, so the selection survives reloads
    const cur = sel.value;
    sel.innerHTML = sel.dataset.opts = opts;
    sel.value = cur;
  }
}

function renderFeatured() {
  $("#spotlight").innerHTML = app.S.profile.interests.filter((i) => i.focus).map(({ name }) => {
    const top = app.S.deals.filter((d) => d.category === name)
      .sort((a, b) => (b.discount_pct || 0) - (a.discount_pct || 0) || (a.unit_price ?? 1e9) - (b.unit_price ?? 1e9) || b.score - a.score)
      .slice(0, 4);
    return top.length ? `<div class="spot"><div class="spot-head"><b>The ${esc(name.toLowerCase())} edit</b>
      <button class="linkish" data-cat-jump="${esc(name)}">see all</button></div>
      <div class="spot-row">${top.map((d) => `
        <a class="spot-card" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.title)}">
          <span class="spot-img">${img(d)}</span>
          <span class="spot-txt"><b>${d.unit_price ? `${usd(d.unit_price)} each` : usd(d.price)}${d.discount_pct ? ` <span class="off">${Math.round(d.discount_pct)}% off</span>` : ""}</b><span class="t">${esc(d.title)}</span>${d.retailer ? `<em>${esc(d.retailer)}</em>` : ""}</span>
        </a>`).join("")}</div></div>` : "";
  }).join("");
}

const dealCard = (d) => {
  const off = d.discount_pct ? Math.round(d.discount_pct) : null;
  const fresh = d.kind !== "product" && Date.now() - new Date(d.posted_at) < DAY;
  const tags = [d.wish_ids.length && `<span class="tagpill wish">♡ on your wishlist</span>`, d.coupon && `<span class="tagpill">code ${esc(d.coupon)}</span>`].filter(Boolean);
  return `
    <a class="deal ${d.kind === "product" ? "product" : ""}" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.summary)}">
      <div class="img">${d.image ? img(d) : `<span class="noimg">✿</span>`}
        ${off ? `<span class="off">${off}% off</span>` : ""}${fresh ? `<span class="new">just in</span>` : ""}</div>
      <div class="body">
        ${d.retailer ? `<span class="r">${esc(d.retailer)}</span>` : ""}
        <div class="title">${esc(d.title)}</div>
        <div class="price">${d.price != null ? `<b>${usd(d.price)}</b>` : ""}${d.orig_price ? `<s>${usd(d.orig_price)}</s>` : ""}</div>
        ${tags.length ? `<div class="tags">${tags.join("")}</div>` : ""}
      </div>
    </a>`;
};

export function renderFeed() {
  const { deals, profile, meta } = app.S;
  const shops = [...new Set(deals.filter((d) => d.kind === "product").map(storeOf))].sort((a, b) => storeRank(a) - storeRank(b) || a.localeCompare(b));
  renderStoreSelect(shops);
  const from = shops.length ? `Sale and new-in picks from ${shops.slice(0, 3).map(esc).join(", ")}${shops.length > 3 ? ` and ${shops.length - 3} more` : ""}` : "Deals from deal-site feeds";
  $("#forYou").innerHTML = `${from}, updated every ${meta.refresh_every_min} minutes · <button class="linkish" data-open-profile>edit preferences</button>`;

  const order = ["Wishlist", ...profile.interests.map((i) => i.name), "Your brands", "Store sales"];
  const cats = [...new Set(deals.map((d) => d.category))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  $("#cats").innerHTML = ["", ...cats].map((c) => `<button class="chip ${view.cat === c ? "on" : ""}" data-cat="${esc(c)}">${esc(c || "Everything")}</button>`).join("");

  renderFeatured();
  const list = filtered();
  $("#deals").innerHTML = list.slice(0, view.shown).map(dealCard).join("") +
    (list.length > view.shown ? `<button class="btn soft small more" id="moreBtn">Show more</button>` : "") ||
    `<div class="empty">Nothing matches that yet. Try another search.</div>`;
}

$("#cats").addEventListener("click", (ev) => {
  const c = ev.target.closest(".chip");
  if (c) { view.cat = c.dataset.cat; view.shown = PAGE; renderFeed(); }
});
$("#spotlight").addEventListener("click", (ev) => {
  const j = ev.target.closest("[data-cat-jump]");
  if (!j) return;
  Object.assign(view, { cat: j.dataset.catJump, shown: PAGE });
  $("#sort").value = "discount";
  renderFeed();
  $("#cats").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#deals").addEventListener("click", (ev) => {
  if (ev.target.id === "moreBtn") { ev.preventDefault(); view.shown += PAGE; renderFeed(); }
});
for (const s of ["#search", "#sort", "#source", "#saleOnly"]) $(s).addEventListener("input", () => { view.shown = PAGE; renderFeed(); });
