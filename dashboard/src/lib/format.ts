export function money(value: number | null | undefined, currency = "INR"): string {
  if (value == null) return "";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
  } catch {
    return `${value.toLocaleString("en-IN")} ${currency}`;
  }
}

/** "5m ago" / "in 3h". */
export function relative(iso: string, now: number = Date.now()): string {
  const s = (now - new Date(iso).getTime()) / 1000;
  const a = Math.abs(s);
  const f = a < 60 ? `${Math.floor(a)}s` : a < 3600 ? `${Math.floor(a / 60)}m` : a < 86400 ? `${Math.floor(a / 3600)}h` : `${Math.floor(a / 86400)}d`;
  return s >= 0 ? `${f} ago` : `in ${f}`;
}

export const humanize = (s: string) => s.replaceAll("_", " ");

/**
 * Parse the hard-line value box: true/false → boolean, numbers → number,
 * comma lists for `in`, otherwise the raw string.
 */
export function parseConditionValue(raw: string, op: string): unknown {
  const v = raw.trim();
  if (v === "true") return true;
  if (v === "false") return false;
  if (op === "in") return v.split(",").map((x) => x.trim()).filter(Boolean);
  if (v !== "" && !Number.isNaN(Number(v))) return Number(v);
  return v;
}
