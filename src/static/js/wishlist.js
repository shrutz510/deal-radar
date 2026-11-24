// Wishlist cards: price now vs. target, progress meter, and details on click.
import { $, api, app, esc, fmtDay, usd } from "./util.js";

const PRIORITY = { 1: "Must have", 2: "Want", 3: "Maybe" };
const LABEL = { hit: "dream price ♡", sale: "on sale", close: "so close", watching: "watching", waiting: "looking…" };
const RANK = { hit: 0, sale: 1, close: 2, watching: 3, waiting: 4 };
const SHOWN = 8;  // cards before "Show all"
const view = { open: new Set(), all: false };

// how close the current price is to the target, 0-100
export const meterPct = (x) => (x.now_price && x.target_price ? Math.min(100, Math.round((x.target_price / x.now_price) * 100)) : 0);
// 'valentino "voce viva" -"10 ml"' -> 'valentino voce viva'
const cleanQuery = (q) => q.replace(/\s-("[^"]*"|\S+)/g, "").replace(/"/g, "");
const link = (url, html, attrs = "") => `<a href="${esc(url)}" target="_blank" rel="noopener" ${attrs}>${html}</a>`;

function details(x) {
  const b = x.best_now, ly = x.last_year;
  const onSale = x.page_price && x.page_regular && x.page_price < x.page_regular;
  const storePrice = x.page_price
    ? `<b>${usd(x.page_price)}</b>${onSale ? ` <s>${usd(x.page_regular)}</s> <span class="save">${Math.round(100 * (1 - x.page_price / x.page_regular))}% off</span>` : ""}`
    : esc(x.page_status || "not checked yet");
  return `<div class="wdetail">
    ${b ? link(b.url, `Best find: <b>${usd(b.price)}</b> ${b.retailer ? `at ${esc(b.retailer)}` : ""} · ${esc(b.title.slice(0, 90))}`, 'class="wbest"') : ""}
    ${x.product_url ? `<div class="page-status">At the store: ${storePrice} · ${link(x.product_url, "open")}</div>` : ""}
    ${x.lowest ? `<div class="lastbf">Lowest this year: <b>${usd(x.lowest)}</b></div>` : ""}
    ${ly ? `<div class="lastbf">${link(ly.url, `Same time last year: <b>${usd(ly.price)}</b> on ${fmtDay(new Date(ly.posted_at))}`, `title="${esc(ly.title)}"`)}${x.target_price ? "" : ` · <button class="linkish" data-target="${x.id}" data-price="${ly.price}">make it my dream price</button>`}</div>` : ""}
    ${x.matches.length ? `<ul class="wmatches">${x.matches.slice(0, 8).map((d) => `<li>${link(d.url, `<span class="p">${usd(d.price)}</span><span class="t">${d.used ? `<em class="used">used</em> ` : ""}${esc(d.title)}</span>`)}</li>`).join("")}</ul>` : ""}
    <div class="wfoot"><span>${PRIORITY[x.priority] || ""}</span><button class="linkish" data-del="${x.id}">Remove</button></div>
  </div>`;
}

function card(x) {
  const open = view.open.has(x.id);
  const sub = !x.now_price ? "No deals spotted yet, still looking" : !x.target_price ? "Tap the price to set your dream price"
    : x.status === "hit" ? "It's at your price, go go go!" : `${usd(x.now_price - x.target_price)} to go`;
  return `
    <div class="wcard ${x.status} ${open ? "open" : ""}" data-toggle="${x.id}">
      <div class="top">
        <div><h3>${esc(cleanQuery(x.query))}</h3>${x.note ? `<div class="note">${esc(x.note)}</div>` : ""}</div>
        <span class="sticker ${x.status}">${LABEL[x.status]}</span>
      </div>
      <div class="wprices">
        <span class="now"><small>now</small>${usd(x.now_price)}</span>
        <span class="goal">dream price <b data-edit="${x.id}" title="Click to change">${x.target_price ? usd(x.target_price) : "set"}</b></span>
      </div>
      <div class="meter"><i style="width:${meterPct(x)}%"></i></div>
      <div class="wsub">${sub}</div>
      ${open ? details(x) : ""}
    </div>`;
}

export function renderWishlist() {
  const w = app.S.wishlist;
  if (!w.length) {
    $("#wishlist").innerHTML = `<div class="empty">Add something you're hoping to buy.<br>Deal Radar looks for it everywhere and pings you when it hits your price.</div>`;
    return;
  }
  const sorted = [...w].sort((a, b) => RANK[a.status] - RANK[b.status] || meterPct(b) - meterPct(a));
  $("#wishlist").innerHTML = (view.all ? sorted : sorted.slice(0, SHOWN)).map(card).join("") +
    (w.length > SHOWN ? `<button class="btn soft small more" data-allwishes>${view.all ? "Show fewer" : `Show all ${w.length} wishes`}</button>` : "");
}

const setTarget = async (id, price) => { await api(`/api/wishlist/${id}`, { method: "PUT", body: { target_price: price } }); app.reload(); };

$("#wishlist").addEventListener("click", async (ev) => {
  const t = ev.target, d = t.dataset;
  if ("allwishes" in d) { view.all = !view.all; return renderWishlist(); }
  if (d.target) return setTarget(d.target, d.price);
  if (d.del) {
    if (confirm("Remove from your wishlist?")) { await api(`/api/wishlist/${d.del}`, { method: "DELETE" }); app.reload(); }
    return;
  }
  if (d.edit) {
    const v = prompt("Dream price in $ (blank to clear):", app.S.wishlist.find((x) => x.id == d.edit).target_price ?? "");
    return v === null ? undefined : setTarget(d.edit, v);
  }
  // anywhere else on the card (but not a link or inside the details) opens/closes it
  const c = t.closest(".wcard");
  if (c && !t.closest("a, button, .wdetail")) {
    const id = +c.dataset.toggle;
    view.open.has(id) ? view.open.delete(id) : view.open.add(id);
    renderWishlist();
  }
});

$("#addWishBtn").addEventListener("click", () => { $("#wishForm").classList.toggle("hidden"); $("#wishForm").query.focus(); });
$("#wishForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/wishlist", { method: "POST", body: Object.fromEntries(new FormData(ev.target)) });
    ev.target.reset();
    ev.target.classList.add("hidden");
    app.reload();
  } catch (e) { alert(e.message); }
});
