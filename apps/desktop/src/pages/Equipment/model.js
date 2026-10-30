// Shared display helpers for the Equipment demo.

export const TYPE_LABEL = { single: "Single", distribution: "Distribution" };

/** A short glyph per category, shown in the row/header icon box. */
export function glyph(item) {
  if (item.type === "distribution") return "▦";
  if (item.categoryId === "transformer") return "⏚";
  if (item.categoryId === "load") return "◎";
  return "▤";
}

/** "2 buses · 3 in · 15 out" for distribution equipment. */
export function busSummary(item) {
  const b = item.buses || [];
  const inc = b.reduce((n, x) => n + x.incomers, 0);
  const out = b.reduce((n, x) => n + x.outgoers, 0);
  return `${b.length} bus${b.length === 1 ? "" : "es"} · ${inc} in · ${out} out`;
}
