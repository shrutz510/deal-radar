// Shared helpers and the one piece of shared state (app).

export const $ = (s) => document.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const usd = (n) => (n == null ? "—" : "$" + (n >= 100 ? Math.round(n).toLocaleString() : n.toFixed(2).replace(/\.00$/, "")));
export const split = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);

// app.S is the latest /api/state; app.reload() fetches it again and re-renders everything.
export const app = { S: null, reload: async () => {} };

export async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body && JSON.stringify(opts.body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* dates: event and countdown dates are plain YYYY-MM-DD in local time */
export const DAY = 86400000;
export const localDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
export const today = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
export const daysBetween = (a, b) => Math.round((b - a) / DAY);
export const fmtDay = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const inDays = (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`);

export function ago(iso) {
  const m = Math.max(0, (Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${Math.round(m)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  if (m < 45 * 1440) return `${Math.round(m / 1440)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}
