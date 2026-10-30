import React, { useCallback, useEffect, useMemo, useState } from "react";
import "../../styles/equipment.css";
import { toast } from "../../components";
import * as api from "../../lib/api/equipment.js";
import { SignIn } from "./SignIn.jsx";
import { EquipmentList } from "./EquipmentList.jsx";
import { DetailPanel } from "./DetailPanel.jsx";

const STEPS = ["Elements", "Mappings", "Schemas", "Tables", "Jobs"];

export function Equipment() {
  // Try the API first; fall back to the sign-in box only if it answers 401/403
  // (with LOGGER_AUTH_DISABLED=1 on the agent, no sign-in is needed).
  const [authed, setAuthed] = useState(true);
  const [categories, setCategories] = useState([]);
  const [items, setItems] = useState([]);
  const [saveState, setSaveState] = useState("saved"); // saved | saving | error
  // Deep link: #eq=<id> opens that equipment.
  const [selectedId, setSelectedIdRaw] = useState(() => {
    const m = /(?:^|[#&])eq=([^&]+)/.exec(window.location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  });
  const setSelectedId = useCallback((id) => {
    setSelectedIdRaw(id);
    try { window.history.replaceState(null, "", id ? `#eq=${encodeURIComponent(id)}` : window.location.pathname); } catch {}
  }, []);

  const onError = useCallback((e) => {
    setSaveState("error");
    if (e && (e.status === 401 || e.status === 403)) {
      setAuthed(false);
      toast.error(e.status === 403 ? "Your account lacks the logger-read/write role" : "Please sign in");
      return;
    }
    toast.error(api.errorText(e));
  }, []);

  const reload = useCallback(async () => {
    try {
      const [cats, list] = await Promise.all([api.listCategories(), api.listEquipment()]);
      setCategories(cats);
      setItems(list);
      setSaveState("saved");
    } catch (e) {
      onError(e);
    }
  }, [onError]);

  useEffect(() => { if (authed) reload(); }, [authed, reload]);

  const changed = useCallback(() => { setSaveState("saving"); reload(); }, [reload]);
  const selected = useMemo(() => items.find((i) => i.id === selectedId), [items, selectedId]);

  if (!authed) return <SignIn onSignedIn={() => setAuthed(true)} />;

  return (
    <div className="eq">
      <header className="eq-appbar">
        <span className="eq-logo">NEURACT</span>
        <nav className="eq-steps">
          {STEPS.map((s, i) => (
            <React.Fragment key={s}>
              {i > 0 && <span className="eq-step-sep">›</span>}
              <span className={`eq-step ${i === 0 ? "active" : ""}`} title={i === 0 ? "" : "Not part of this demo"}>{s}</span>
            </React.Fragment>
          ))}
        </nav>
      </header>

      <div className="eq-page">
        <section className="eq-left">
          <div className="eq-head">
            <h2 className="eq-title">Electrical Equipment</h2>
            <div className="eq-subtitle">Add equipment. Distribution equipment (LT / HT panels) has buses.</div>
          </div>
          <EquipmentList
            categories={categories}
            items={items}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onChanged={changed}
            onError={onError}
          />
          <footer className="eq-footer">
            <span className={`eq-save ${saveState}`}>
              {saveState === "saving" ? "Saving…" : saveState === "error" ? "Last change failed" : "All changes saved"}
            </span>
          </footer>
        </section>

        <section className="eq-right">
          {selected ? (
            <DetailPanel
              key={selected.id}
              item={selected}
              items={items}
              categories={categories}
              onOpen={setSelectedId}
              onClose={() => setSelectedId(null)}
              onChanged={changed}
              onDeleted={() => { setSelectedId(null); changed(); }}
              onError={onError}
            />
          ) : (
            <div className="eq-empty">Select equipment to see its details.</div>
          )}
        </section>
      </div>
    </div>
  );
}
