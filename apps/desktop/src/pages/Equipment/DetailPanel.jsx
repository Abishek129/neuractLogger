import React, { useState } from "react";
import { toast } from "../../components";
import * as api from "../../lib/api/equipment.js";
import { TYPE_LABEL, busSummary, glyph } from "./model.js";

const MAX_BUSES = 8;

/** A whole-number input that saves itself on blur / Enter. */
function CountInput({ value, onSave }) {
  const [text, setText] = useState(String(value));
  React.useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const t = text.trim();
    if (!/^\d+$/.test(t) || Number(t) > 999) { toast.error("Enter a whole number 0–999"); setText(String(value)); return; }
    if (Number(t) !== value) onSave(Number(t));
  };
  return (
    <input
      className="eq-count"
      inputMode="numeric"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

/** Toggle chips: which equipment categories may sit on this side of the bus. */
function CategoryChips({ label, selected, categories, onSave }) {
  const toggle = (id) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    onSave(next);
  };
  return (
    <div className="eq-bus-cats">
      <span className="eq-bus-cats-label">{label}</span>
      {categories.map((c) => (
        <button
          key={c.id}
          className={`eq-chip small ${selected.includes(c.id) ? "active" : ""}`}
          onClick={() => toggle(c.id)}
          title={selected.includes(c.id) ? "Allowed — click to remove" : "Click to allow"}
        >
          {c.name}
        </button>
      ))}
      {!selected.length && <span className="eq-muted">any category</span>}
    </div>
  );
}

/** One side of a bus: the attached equipment, spares, and an attach picker. */
function AttachedSide({ bus, role, items, panelId, onOpen, onChanged, onError }) {
  const [pick, setPick] = useState("");
  const list = role === "incomer" ? bus.incomingEquipment : bus.outgoingEquipment;
  const allowed = role === "incomer" ? bus.incomingCategories : bus.outgoingCategories;
  const spare = role === "incomer" ? bus.spareIncomers : bus.spareOutgoers;
  const onBus = new Set([...bus.incomingEquipment, ...bus.outgoingEquipment].map((e) => e.id));
  const candidates = items.filter(
    (i) => i.id !== panelId && !onBus.has(i.id) && (!allowed.length || allowed.includes(i.categoryId)),
  );
  const attach = async () => {
    try { await api.attachEquipment(bus.id, pick, role); setPick(""); onChanged(); } catch (e) { onError(e); }
  };
  const detach = async (id) => {
    try { await api.detachEquipment(bus.id, id); onChanged(); } catch (e) { onError(e); }
  };
  return (
    <div className="eq-attached">
      {list.map((e) => (
        <span key={e.id} className="eq-attached-item">
          <button className="eq-link eq-mono" onClick={() => onOpen(e.id)}>{e.name}</button>
          <span className="eq-muted">{e.categoryName}</span>
          <button className="eq-icon" title="Detach" onClick={() => detach(e.id)}>✕</button>
        </span>
      ))}
      {spare > 0 ? (
        <span className="eq-inline">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">{`Attach… (${spare} spare)`}</option>
            {candidates.map((i) => <option key={i.id} value={i.id}>{i.name} — {i.categoryName}</option>)}
          </select>
          {pick && <button className="eq-btn primary small" onClick={attach}>Attach</button>}
        </span>
      ) : (
        <span className="eq-muted">{list.length ? "full" : "no places — raise the count"}</span>
      )}
    </div>
  );
}

function BusRow({ bus, categories, items, panelId, onOpen, canDelete, onChanged, onError }) {
  const save = async (patch) => {
    try { await api.updateBus(bus.id, patch); onChanged(); } catch (e) { onError(e); }
  };
  const rename = () => {
    const next = window.prompt("Rename bus", bus.name);
    if (next && next.trim() !== bus.name) save({ name: next.trim() });
  };
  const remove = async () => {
    try { await api.deleteBus(bus.id); onChanged(); } catch (e) { onError(e); }
  };
  return (
    <div className="eq-bus">
      <div className="eq-bus-head">
        <span className="eq-bus-name">{bus.name}</span>
        <button className="eq-icon" title="Rename bus" onClick={rename}>✎</button>
        <span className="eq-bus-counts">
          <label>Incomers <CountInput value={bus.incomers} onSave={(n) => save({ incomers: n })} /></label>
          <label>Outgoers <CountInput value={bus.outgoers} onSave={(n) => save({ outgoers: n })} /></label>
        </span>
        <button className="eq-icon" title={canDelete ? "Delete bus" : "The last bus can't be deleted"} disabled={!canDelete} onClick={remove}>✕</button>
      </div>
      <CategoryChips label="Incoming" selected={bus.incomingCategories} categories={categories}
        onSave={(ids) => save({ incomingCategories: ids })} />
      <AttachedSide bus={bus} role="incomer" items={items} panelId={panelId} onOpen={onOpen} onChanged={onChanged} onError={onError} />
      <CategoryChips label="Outgoing" selected={bus.outgoingCategories} categories={categories}
        onSave={(ids) => save({ outgoingCategories: ids })} />
      <AttachedSide bus={bus} role="outgoer" items={items} panelId={panelId} onOpen={onOpen} onChanged={onChanged} onError={onError} />
    </div>
  );
}

/** MFMs attached to this equipment: list + attach picker (unattached devices only). */
function Meters({ item, onChanged, onError }) {
  const [free, setFree] = useState([]);
  const [pick, setPick] = useState("");
  const meterKey = item.meters.map((m) => m.deviceId).join(",");
  React.useEffect(() => {
    api.availableMeters().then(setFree).catch(onError);
  }, [meterKey, onError]);
  const attach = async () => {
    try { await api.attachMeter(item.id, pick); setPick(""); onChanged(); } catch (e) { onError(e); }
  };
  const detach = async (deviceId) => {
    try { await api.detachMeter(item.id, deviceId); onChanged(); } catch (e) { onError(e); }
  };
  return (
    <section className="eq-section">
      <h4>MFMs</h4>
      {item.meters.map((m) => (
        <div key={m.deviceId} className="eq-strip eq-meter-row">
          <span className={`eq-dot ${m.status === "connected" ? "ok" : "off"}`} title={m.status || "unknown"} />
          <span className="eq-mono">{m.deviceName || m.deviceId}</span>
          <span className="eq-muted">{m.protocol}</span>
          <button className="eq-icon eq-strip-go" title="Detach MFM" onClick={() => detach(m.deviceId)}>✕</button>
        </div>
      ))}
      {!item.meters.length && <p className="eq-muted">No MFM attached.</p>}
      <span className="eq-inline">
        <select value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">{free.length ? "Attach an MFM…" : "No unattached devices"}</option>
          {free.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        {pick && <button className="eq-btn primary small" onClick={attach}>Attach</button>}
      </span>
    </section>
  );
}

export function DetailPanel({ item, items, categories, onOpen, onClose, onChanged, onDeleted, onError }) {
  const isDist = item.type === "distribution";
  // A category change must keep the type (single <-> distribution is not allowed).
  const sameType = categories.filter((c) => c.type === item.type);

  const update = async (patch) => {
    try { await api.updateEquipment(item.id, patch); onChanged(); } catch (e) { onError(e); }
  };
  const rename = () => {
    const next = window.prompt("Rename equipment", item.name);
    if (next && next.trim() !== item.name) update({ name: next.trim() });
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${item.name}?${isDist ? " Its buses are deleted too." : ""}`)) return;
    try { await api.deleteEquipment(item.id); toast.success(`${item.name} deleted`); onDeleted(); } catch (e) { onError(e); }
  };
  const setCount = async (n) => {
    try { await api.setBusCount(item.id, n); onChanged(); } catch (e) { onError(e); }
  };

  return (
    <div className="eq-detail">
      <div className="eq-detail-head">
        <span className="eq-glyph big">{glyph(item)}</span>
        <div className="eq-detail-id">
          <div className="eq-detail-title">
            <span className="eq-mono">{item.name}</span>
            <button className="eq-icon" title="Rename" onClick={rename}>✎</button>
          </div>
          <div className="eq-tags">
            <select className="eq-nav-select" value={item.categoryId} onChange={(e) => update({ categoryId: e.target.value })} title="Category">
              {sameType.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <span className={`eq-badge ${isDist ? "ok" : "plain"}`}>{TYPE_LABEL[item.type]}</span>
            {isDist && <span className="eq-muted">{busSummary(item)}</span>}
          </div>
        </div>
        <div className="eq-detail-actions">
          <button className="eq-btn ghost small danger" onClick={remove}>Delete</button>
          <button className="eq-icon" title="Close" onClick={onClose}>✕</button>
        </div>
      </div>

      <Meters item={item} onChanged={onChanged} onError={onError} />

      {item.attachedTo.length > 0 && (
        <section className="eq-section">
          <h4>Attached to</h4>
          {item.attachedTo.map((a) => (
            <div key={a.busId} className="eq-placed">
              <button className="eq-link" onClick={() => onOpen(a.equipmentId)}>{a.equipmentName} · {a.busName}</button>
              <span className="eq-muted">as {a.role}</span>
            </div>
          ))}
        </section>
      )}

      {isDist ? (
        <section className="eq-section">
          <div className="eq-section-head">
            <h4>Buses</h4>
            <label className="eq-inline">
              <span className="eq-field-label">Bus sections</span>
              <select value={item.buses.length} onChange={(e) => setCount(Number(e.target.value))}>
                {Array.from({ length: Math.max(MAX_BUSES, item.buses.length) }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          </div>
          {item.buses.map((b) => (
            <BusRow key={b.id} bus={b} categories={categories} items={items} panelId={item.id} onOpen={onOpen} canDelete={item.buses.length > 1} onChanged={onChanged} onError={onError} />
          ))}
        </section>
      ) : (
        <section className="eq-section">
          <p className="eq-muted">{item.categoryName} is single equipment: it has no buses.</p>
        </section>
      )}

      <section className="eq-section">
        <h4>Description</h4>
        <textarea
          className="eq-notes"
          rows={2}
          defaultValue={item.description || ""}
          key={item.description || ""}
          onBlur={(e) => {
            const v = e.target.value.trim() || null;
            if (v !== (item.description || null)) update({ description: v });
          }}
        />
      </section>
    </div>
  );
}
