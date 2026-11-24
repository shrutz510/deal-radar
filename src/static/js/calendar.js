// Sale dates: tickets for live and upcoming events, plus the "add a date" form.
import { $, api, app, daysBetween, esc, fmtDay, inDays, localDate, today } from "./util.js";

function span(e) {
  const start = localDate(e.start);
  // an event without an end date is drawn as running for a week
  const end = e.end ? localDate(e.end) : new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7);
  return { start, end, open: !e.end };
}

function status({ start, end }) {
  const t = today();
  if (t < start) return { kind: "upcoming", days: daysBetween(t, start) };
  if (t <= end) return { kind: "live", days: daysBetween(t, end) };
  return { kind: "past" };
}

export function renderCalendar() {
  const evs = app.S.events.map((e) => { const s = span(e); return { e, ...s, st: status(s) }; })
    .filter((x) => x.st.kind !== "past")
    .sort((a, b) => (b.st.kind === "live") - (a.st.kind === "live") || a.start - b.start);
  $("#timeline").innerHTML = evs.map(({ e, st, start, end, open }) => {
    const range = open ? `from ${fmtDay(start)}` : +start === +end ? fmtDay(start) : `${fmtDay(start)} – ${fmtDay(end)}`;
    const when = st.kind === "live" ? (open ? range : `ends ${inDays(st.days)}`) : `${range} · ${inDays(st.days)}`;
    const tip = [e.note, e.status === "mine" ? "Added by you · double-click to delete" : "", e.url ? "Click to open the sale page" : ""].filter(Boolean).join("\n");
    const tag = { expected: "expected", mine: "added by you" }[e.status];
    return `
      <div class="ticket ${e.retailer === "Everyone" ? "key" : ""} ${st.kind === "live" ? "live" : ""}" data-ev="${e.id}" title="${esc(tip)}">
        <div class="tdate"><b>${start.getDate()}</b><span>${start.toLocaleDateString("en-US", { month: "short" })}</span></div>
        <div class="tbody">
          <span class="tstore">${esc(e.retailer === "Everyone" ? "Everywhere" : e.retailer)}</span>
          <span class="tname">${esc(e.name)}</span>
          <span class="twhen">${when}</span>
          ${tag ? `<span class="tag">${tag}</span>` : ""}
        </div>
      </div>`;
  }).join("") || `<div class="empty">No sales coming up. Add one with “Add a date”.</div>`;
}

const eventOf = (el) => el && app.S.events.find((x) => x.id == el.dataset.ev);

$("#timeline").addEventListener("click", (ev) => {
  const e = eventOf(ev.target.closest(".ticket"));
  if (e?.url) window.open(e.url, "_blank", "noopener");
});
$("#timeline").addEventListener("dblclick", async (ev) => {
  const e = eventOf(ev.target.closest(".ticket"));
  if (e?.status === "mine" && confirm(`Delete "${e.name}"?`)) {
    await api(`/api/events/${e.id}`, { method: "DELETE" });
    app.reload();
  }
});
$("#addEventBtn").addEventListener("click", () => $("#eventForm").classList.toggle("hidden"));
$("#eventForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/events", { method: "POST", body: Object.fromEntries(new FormData(ev.target)) });
  ev.target.reset();
  ev.target.classList.add("hidden");
  app.reload();
});
