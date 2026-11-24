// Setup screen: a few questions that the server turns into a profile (profiles.build_profile).
// Stores are suggested from the department and categories until the user picks stores by hand.
import { $, api, app, esc, split } from "./util.js";

const form = $("#setupForm");
let storesTouched = false;

export const isSetupOpen = () => !$("#setup").classList.contains("hidden");
const options = () => app.S.setup_options;
const checked = (name) => [...form.querySelectorAll(`[name="${name}"]:checked`)].map((i) => i.value);
const pick = (type, name, value, label, on, extra = "") =>
  `<label class="pick"><input type="${type}" name="${name}" value="${esc(value)}" ${on ? "checked" : ""}><span>${esc(label)}${extra}</span></label>`;
const customRow = (c = { name: "", keywords: [] }) => `
  <div class="irow custom"><input name="cname" placeholder="Category name, e.g. Board games" value="${esc(c.name)}">
  <textarea name="ckeys" rows="1" placeholder="words to look for in deal titles, comma-separated">${esc((c.keywords || []).join(", "))}</textarea>
  <button type="button" class="linkish" data-rmc>Remove</button></div>`;

function suggestedStores() {
  const dept = checked("department")[0] || "all", cats = checked("cat");
  return Object.entries(options().stores)
    .filter(([, s]) => s.sells.some((c) => cats.includes(c)) && (dept === "all" || s.for === "all" || s.for === dept))
    .map(([name]) => name);
}

// keep the suggested stores and the "feature one category" choices in step with the answers
function sync() {
  if (!storesTouched) {
    const want = suggestedStores();
    form.querySelectorAll('[name="shop"]').forEach((i) => (i.checked = want.includes(i.value)));
  }
  const names = [...checked("cat"), ...[...form.querySelectorAll("[name=cname]")].map((i) => i.value.trim()).filter(Boolean)];
  const sel = form.featured, cur = sel.value;
  sel.innerHTML = `<option value="">None</option>` + names.map((n) => `<option>${esc(n)}</option>`).join("");
  sel.value = names.includes(cur) ? cur : "";
}

function fill(a = {}) {
  const o = options();
  form.title.value = a.title || "";
  form.about.value = a.about || "";
  form.brands.value = (a.brands || []).join(", ");
  form.avoid.value = (a.avoid || []).join(", ");
  form.hide_common.checked = a.hide_common !== false;
  form.countdown_label.value = a.countdown?.label || "";
  form.countdown_date.value = a.countdown?.date || "";
  $("#setupDept").innerHTML = Object.entries(o.departments).map(([k, v]) => pick("radio", "department", k, v, (a.department || "all") === k)).join("");
  $("#setupCats").innerHTML = o.categories.map((c) => pick("checkbox", "cat", c, c, (a.categories || []).includes(c))).join("");
  $("#setupCustom").innerHTML = (a.custom || []).map(customRow).join("");
  const shops = a.shops || [];
  $("#setupStores").innerHTML = Object.entries(o.stores).map(([n, s]) => pick("checkbox", "shop", n, n, shops.includes(n), `<small>${esc(s.sells.join(", "))}</small>`)).join("");
  storesTouched = shops.length > 0;  // an explicit store list is kept; otherwise follow the suggestions
  form.sale_dates.innerHTML = `<option value="">None</option>` + o.sale_dates.map((n) => `<option>${esc(n)}</option>`).join("");
  form.sale_dates.value = a.sale_dates || "";
  sync();
  form.featured.value = a.featured || "";
}

export function openSetup(cancelable) {
  if (!isSetupOpen()) {
    $("#presets").innerHTML = Object.keys(options().presets).map((n) => `<button type="button" class="btn soft small" data-preset="${esc(n)}">${esc(n)}</button>`).join("");
    fill(app.S.profile?.setup);
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

function answers() {
  const custom = [...form.querySelectorAll(".irow.custom")]
    .map((r) => ({ name: r.querySelector("[name=cname]").value.trim(), keywords: split(r.querySelector("[name=ckeys]").value) }))
    .filter((c) => c.name);
  const shops = checked("shop");
  return {
    title: form.title.value.trim(), about: form.about.value.trim(),
    department: checked("department")[0] || "all", categories: checked("cat"), custom, featured: form.featured.value,
    // every store ticked means "all stores", which also picks up stores added later
    shops: shops.length === Object.keys(options().stores).length ? [] : shops,
    brands: split(form.brands.value), hide_common: form.hide_common.checked, avoid: split(form.avoid.value),
    countdown: form.countdown_date.value ? { label: form.countdown_label.value.trim(), date: form.countdown_date.value } : null,
    sale_dates: form.sale_dates.value,
  };
}

form.addEventListener("change", (ev) => {
  if (ev.target.name === "shop") storesTouched = true;
  if (["department", "cat", "cname"].includes(ev.target.name)) sync();
});
form.addEventListener("click", (ev) => {
  const preset = ev.target.closest("[data-preset]");
  if (preset) fill(options().presets[preset.dataset.preset]);
  if (ev.target.closest("[data-rmc]")) { ev.target.closest(".irow").remove(); sync(); }
});
$("#addCustom").addEventListener("click", () => $("#setupCustom").insertAdjacentHTML("beforeend", customRow()));
$("#setupCancel").addEventListener("click", closeSetup);
form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const a = answers();
  if (!a.categories.length && !a.custom.length) return alert("Pick at least one category, or add your own.");
  await api("/api/setup", { method: "PUT", body: a });
  closeSetup();
  app.reload({ resetFeed: true });
});
