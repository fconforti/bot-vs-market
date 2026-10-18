import data from "../data/site.json";

export const site = data as any;

const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
/** Link to a page or asset inside the site, honouring the GitHub Pages base path. */
export const url = (p = "") => `${BASE}/${p.replace(/^\//, "")}`;

export const NAV = [
  { href: "", label: "Overview", icon: "overview" },
  { href: "journal/", label: "Journal", icon: "journal" },
  { href: "trades/", label: "Trades", icon: "trades" },
  { href: "portfolio/", label: "Portfolio", icon: "portfolio" },
  { href: "strategy/", label: "Strategy", icon: "strategy" },
  { href: "research/", label: "Research", icon: "research" },
  { href: "mistakes/", label: "Mistakes", icon: "mistakes" },
  { href: "glossary/", label: "Glossary", icon: "glossary" },
  { href: "about/", label: "About", icon: "about" },
];

const eurFmt = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", minimumFractionDigits: 2 });
export const eur = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "—" : eurFmt.format(v));
export const pct = (v: number | null | undefined, digits = 2, signed = true) =>
  v == null || Number.isNaN(v) ? "—" : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
export const tone = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "pos" : "neg");

export const statusTone = (s?: string | null) => {
  const k = (s || "").toLowerCase();
  if (["executed", "ok", "completed", "done"].some((w) => k.includes(w))) return "good";
  if (["rejected", "aborted", "unknown", "error", "failed"].some((w) => k.includes(w))) return "bad";
  if (["proposed", "pending", "no trade", "no-trade", "hold"].some((w) => k.includes(w))) return "info";
  return "";
};

export const fmtDate = (d?: string | null) => {
  if (!d) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return d;
  const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};
