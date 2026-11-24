// Preferences: edit the profile setup generated (sections, keywords, brands, stores, hidden words).
import { $, api, app, esc, split } from "./util.js";
import { openSetup } from "./setup.js";

const modal = $("#profileModal"), form = $("#profileForm");
const list = (xs) => (xs || []).join(", ");
const sectionRow = (i = { name: "", keywords: [] }) => `
  <div class="irow"><div class="iname"><input name="iname" placeholder="Section name" value="${esc(i.name)}">
  <label class="star" title="Feature this section at the top"><input type="checkbox" name="ifocus" ${i.focus ? "checked" : ""}> ★ Featured</label></div>
  <textarea name="ikeys" rows="1" placeholder="keywords, comma-separated">${esc(list(i.keywords))}</textarea>
  <button type="button" class="linkish" data-rm>Remove</button></div>`;
const close = () => modal.classList.add("hidden");

function openPrefs() {
  const p = app.S.profile;
  for (const f of ["brands", "stores", "shops", "avoid"]) form[f].value = list(p[f]);
  form.about.value = p.about || "";
  $("#shopsHint").textContent = `leave empty to browse every store: ${Object.keys(app.S.setup_options.stores).join(", ")}`;
  $("#interests").innerHTML = (p.interests || []).map(sectionRow).join("");
  modal.classList.remove("hidden");
}

$("#profileBtn").addEventListener("click", openPrefs);
document.addEventListener("click", (ev) => { if (ev.target.closest("[data-open-profile]")) openPrefs(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") close(); });
modal.addEventListener("click", (ev) => {
  if (ev.target === modal || ev.target.closest("[data-close]")) close();
  if (ev.target.closest("[data-rm]")) ev.target.closest(".irow").remove();
});
$("#addInterest").addEventListener("click", () => $("#interests").insertAdjacentHTML("beforeend", sectionRow()));
$("#rerunSetup").addEventListener("click", () => { close(); openSetup(true); });
$("#resetProfile").addEventListener("click", async () => {
  if (!confirm("Start over? Your preferences are cleared and setup opens again. The wishlist is kept.")) return;
  await api("/api/profile/reset", { method: "PUT" });
  close();
  app.reload();
});
form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const interests = [...form.querySelectorAll(".irow")].map((r) => ({
    name: r.querySelector("[name=iname]").value, keywords: split(r.querySelector("[name=ikeys]").value),
    focus: r.querySelector("[name=ifocus]").checked }));
  const body = { about: form.about.value, interests };
  for (const f of ["brands", "stores", "shops", "avoid"]) body[f] = split(form[f].value);
  await api("/api/profile", { method: "PUT", body });
  close();
  app.reload({ resetFeed: true });
});
