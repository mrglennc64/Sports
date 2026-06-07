// Central backend base URL. Override with VITE_API_BASE at build/dev time.
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function fetchSlate(date, minEdge) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (minEdge != null && minEdge !== "") params.set("min_edge", minEdge);
  const res = await fetch(`${BASE}/slate?${params.toString()}`);
  if (!res.ok) throw new Error(`slate request failed: ${res.status}`);
  return res.json();
}
