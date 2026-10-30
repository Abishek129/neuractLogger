import React, { useMemo, useState } from "react";
import { toast } from "../../components";
import * as api from "../../lib/api/equipment.js";
import { TYPE_LABEL, busSummary, glyph } from "./model.js";

function CreateRow({ categories, defaultCategory, onCreated, onCancel, onError }) {
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState(defaultCategory || categories[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const cat = categories.find((c) => c.id === categoryId);

  const submit = async (ev) => {
    ev.preventDefault();
    setBusy(true);
    try {
      const item = await api.createEquipment({ name: name.trim(), categoryId });
      toast.success(`${item.name} created`);
      onCreated(item);
    } catch (e) { onError(e); } finally { setBusy(false); }
  };
  return (
    <form className="eq-create" onSubmit={submit} onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <span className="eq-glyph">+</span>
      <input autoFocus className="eq-mono eq-create-name" placeholder="Equipment name" value={name} onChange={(e) => setName(e.target.value)} />
      <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} title="Category">
        {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <span className="eq-create-hint">
        {cat ? `${TYPE_LABEL[cat.type]}${cat.type === "distribution" ? " — starts with Bus A" : ""}` : ""}
      </span>
      <button className="eq-btn primary small" disabled={busy || !name.trim() || !categoryId}>Done</button>
      <button type="button" className="eq-btn ghost small" onClick={onCancel}>Cancel</button>
    </form>
  );
}

function RowMenu({ item, onSelect, onChanged, onError }) {
  const [open, setOpen] = useState(false);
  const remove = async () => {
    setOpen(false);
    if (!window.confirm(`Delete ${item.name}?${item.type === "distribution" ? " Its buses are deleted too." : ""}`)) return;
    try { await api.deleteEquipment(item.id); toast.success(`${item.name} deleted`); onChanged(); } catch (e) { onError(e); }
  };
  return (
    <span className="eq-menu" onClick={(e) => e.stopPropagation()}>
      <button className="eq-icon" title="More" onClick={() => setOpen(!open)}>⋯</button>
      {open && (
        <span className="eq-menu-pop" onMouseLeave={() => setOpen(false)}>
          <button onClick={() => { setOpen(false); onSelect(item.id); }}>Open</button>
          <button className="danger" onClick={remove}>Delete</button>
        </span>
      )}
    </span>
  );
}

export function EquipmentList({ categories, items, selectedId, onSelect, onChanged, onError }) {
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((i) => (!filter || i.categoryId === filter) && (!q || i.name.toLowerCase().includes(q)));
  }, [items, filter, query]);
  const count = (cid) => items.filter((i) => i.categoryId === cid).length;

  return (
    <div className="eq-list">
      <div className="eq-navs">
        <button className={`eq-chip ${!filter ? "active" : ""}`} onClick={() => setFilter("")}>All ({items.length})</button>
        {categories.map((c) => (
          <button key={c.id} className={`eq-chip ${filter === c.id ? "active" : ""}`} onClick={() => setFilter(c.id)}>
            {c.name} ({count(c.id)})
          </button>
        ))}
      </div>
      <div className="eq-toolbar">
        <input className="eq-search" placeholder="Search equipment…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="eq-btn primary" onClick={() => setCreating(true)} disabled={creating}>+ Add</button>
      </div>
      <div className="eq-table">
        <div className="eq-table-head"><span>Equipment</span><span>Buses</span></div>
        <div className="eq-rows">
          {creating && (
            <CreateRow
              categories={categories}
              defaultCategory={filter}
              onCancel={() => setCreating(false)}
              onCreated={(item) => { setCreating(false); onChanged(); onSelect(item.id); }}
              onError={onError}
            />
          )}
          {shown.map((i) => (
            <div
              key={i.id}
              role="button"
              tabIndex={0}
              className={`eq-row ${i.id === selectedId ? "selected" : ""}`}
              onClick={() => onSelect(i.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(i.id)}
            >
              <span className="eq-glyph">{glyph(i)}</span>
              <span className="eq-row-main">
                <span className="eq-row-name eq-mono">{i.name}</span>
                <span className="eq-row-sub">{i.categoryName} · {TYPE_LABEL[i.type]}</span>
              </span>
              <span className="eq-row-side">
                {i.type === "distribution"
                  ? <span className="eq-badge plain">{busSummary(i)}</span>
                  : <span className="eq-row-usage">—</span>}
              </span>
              <RowMenu item={i} onSelect={onSelect} onChanged={onChanged} onError={onError} />
            </div>
          ))}
          {!shown.length && !creating && (
            <div className="eq-empty">{items.length ? "No equipment matches." : "No equipment yet. Use + Add."}</div>
          )}
        </div>
      </div>
    </div>
  );
}
