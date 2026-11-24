// Entry point: load /api/state, render every section, keep the top bar current.
import { $, ago, api, app, daysBetween, esc, localDate, today } from "./util.js";
import { renderCalendar } from "./calendar.js";
import { renderFeed, resetFeed } from "./feed.js";
import { renderWishlist } from "./wishlist.js";
import { isSetupOpen, openSetup } from "./setup.js";
import "./prefs.js";

function renderTopBar() {
  const { profile, meta } = app.S;
  $("#appTitle").textContent = document.title = profile.title || "Deal Radar";
  const c = profile.countdown, days = c ? daysBetween(today(), localDate(c.date)) : -1;
  $("#countdown").textContent = days > 1 ? `${days} days to ${c.label}` : days === 1 ? `${c.label} is tomorrow` : days === 0 ? `It's ${c.label} ♡` : "";
  const failed = Object.entries(meta.sources || {}).filter(([, v]) => !v.ok);
  $("#updated").innerHTML = (meta.last_refresh ? `Updated ${ago(meta.last_refresh)}` : "Not refreshed yet") +
    (failed.length ? ` · <span title="${esc(failed.map(([k, v]) => `${k}: ${v.error}`).join("\n"))}">${failed.length} store${failed.length > 1 ? "s" : ""} didn't load</span>` : "");
}

function render() {
  if (app.S.needs_setup) return openSetup(false);
  if (!isSetupOpen()) $("#app").classList.remove("hidden");
  renderTopBar();
  renderCalendar();
  renderWishlist();
  renderFeed();
}

app.reload = async ({ resetFeed: reset } = {}) => {
  if (reset) resetFeed();
  app.S = await api("/api/state");
  render();
  const btn = $("#refreshBtn"), busy = app.S.meta.refreshing;
  btn.classList.toggle("spinning", busy);
  btn.querySelector("span").textContent = busy ? "Refreshing…" : "Refresh";
  if (busy) setTimeout(app.reload, 2500);  // poll until the refresh finishes
};

$("#refreshBtn").addEventListener("click", async () => { await api("/api/refresh", { method: "POST" }); app.reload(); });

// theme: auto (follows the OS setting) -> light -> dark; remembered in localStorage
const THEMES = { auto: ["◐", "Auto"], light: ["☀", "Light"], dark: ["☾", "Dark"] };
function setTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch (e) {}
  $("#themeBtn").innerHTML = `<span>${THEMES[t][0]}</span><span class="lbl">${THEMES[t][1]}</span>`;
}
$("#themeBtn").addEventListener("click", () => setTheme({ auto: "light", light: "dark", dark: "auto" }[document.documentElement.dataset.theme || "auto"]));
setTheme(document.documentElement.dataset.theme || "auto");

app.reload();
setInterval(app.reload, 5 * 60 * 1000);
