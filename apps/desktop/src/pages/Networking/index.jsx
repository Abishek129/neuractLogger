import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "../../state/store.jsx";
import {
  selectReachability,
  selectDevices,
  selectDbTargets,
  selectDefaultDbTargetId,
  selectHasConnectedDevice,
  selectDbDefaultOk,
  selectGateways,
} from "../../state/selectors.js";
import "../../styles/networking.css";
import { toast } from "../../components/Toast.jsx";

function ipToInt(ip) {
  const parts = (ip || "").split(".").map((n) => parseInt(n, 10));
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return 0;
  return (
    ((parts[0] << 24) >>> 0) + (parts[1] << 16) + (parts[2] << 8) + parts[3]
  );
}

function cidrToMask(cidr) {
  const n = Math.max(0, Math.min(32, +cidr || 0));
  return n === 0 ? 0 : (0xffffffff << (32 - n)) >>> 0;
}

function Dot({ status }) {
  const color =
    status === "connected" || status === "ok"
      ? "#22a06b"
      : status === "degraded"
      ? "#b37feb"
      : status === "connecting" || status === "reconnecting"
      ? "#f59e0b"
      : status === "fail"
      ? "#ef4444"
      : "#9ca3af";
  return (
    <span
      className="dot"
      style={{ backgroundColor: color }}
      aria-hidden="true"
    />
  );
}

export function Networking({ onProceed }) {
  const { state, dispatch } = useApp();
  const reach = selectReachability(state);
  const devices = selectDevices(state);
  const targets = selectDbTargets(state);
  const defaultTargetId = selectDefaultDbTargetId(state);
  const hasConnected = selectHasConnectedDevice(state);
  const defaultOk = selectDbDefaultOk(state);
  const gateways = selectGateways(state);

  const [left, setLeft] = useState("reachability"); // 'reachability' | 'gateways' | 'connect' | 'devices' | 'databases'
  const [selectedDeviceId, setSelectedDeviceId] = useState(null);

  // Reachability helpers
  const adapter = useMemo(
    () =>
      reach.adapters.find((a) => a.id === reach.adapterId) || reach.adapters[0],
    [reach]
  );
  const subnetHint = useMemo(() => {
    const tip = (target) => {
      const ipInt = ipToInt(target);
      const aInt = ipToInt(adapter?.ip);
      const mask = cidrToMask(adapter?.cidr);
      if (!ipInt || !aInt || !mask) return "";
      return (ipInt & mask) === (aInt & mask)
        ? "Same subnet"
        : "Different subnet";
    };
    return tip(reach.target);
  }, [adapter, reach.target]);

  const [gwName, setGwName] = useState("");
  const [gwEditingId, setGwEditingId] = useState(null);
  const [gwDraft, setGwDraft] = useState({
    name: "",
    host: "",
    ports: [],
    protocol_hint: "",
    nic_hint: "",
  });
  const [gwBusyIds, setGwBusyIds] = useState(new Set());

  const runPing = async () => {
    try {
      dispatch({ type: "NET_PING_PENDING" });
      const { pingTarget } = await import("../../lib/api/networking.js");
      const res = await pingTarget({
        target: reach.target || "127.0.0.1",
        count: 4,
        timeoutMs: 800,
      });
      const success = !!res.ok;
      const lossPct = res.lossPct ?? (success ? 0 : 100);
      const min = res.min ?? 0,
        avg = res.avg ?? 0,
        max = res.max ?? 0;
      const samples = res.samples || [];
      dispatch({
        type: "NET_SET_PING_RESULT",
        result: { success, lossPct, min, avg, max, samples, timeMs: 0 },
      });
    } catch (e) {
      console.error("Ping request failed:", e);
      dispatch({
        type: "NET_SET_PING_RESULT",
        result: {
          success: false,
          lossPct: 100,
          min: 0,
          avg: 0,
          max: 0,
          samples: [],
          timeMs: 0,
        },
      });
    }
  };

  const runPortTests = async (ports) => {
    try {
      dispatch({ type: "NET_PORTS_PENDING" });
      const { tcpTest } = await import("../../lib/api/networking.js");
      const results = [];
      for (const p of ports) {
        const r = await tcpTest({
          host: reach.target || "127.0.0.1",
          port: p,
          timeoutMs: 1000,
        });
        results.push({ port: p, status: r.status, timeMs: r.timeMs ?? 0 });
      }
      dispatch({ type: "NET_SET_PORT_RESULTS", results });
    } catch (e) {
      console.error("TCP tests failed:", e);
      dispatch({
        type: "NET_SET_PORT_RESULTS",
        results: ports.map((p) => ({ port: p, status: "timeout", timeMs: 0 })),
      });
    }
  };
  // Saved Gateways helpers
  const addGatewayQuick = async () => {
    try {
      const { addGateway } = await import("../../lib/api/networking.js");
      const name = (gwDraft.name || "").trim();
      const host = (gwDraft.host || "").trim();
      if (!name || !host) return;
      const payload = {
        name,
        host,
        ports: gwDraft.ports || [],
        protocol_hint: gwDraft.protocol_hint || undefined,
        nic_hint: gwDraft.nic_hint || undefined,
      };
      const res = await addGateway(payload);
      if (res?.item) {
        dispatch({ type: "GW_ADD", gateway: res.item });
        setGwDraft({
          name: "",
          host: "",
          ports: [],
          protocol_hint: "",
          nic_hint: "",
        });
      }
    } catch {}
  };
  const pingGw = async (g) => {
    try {
      setGwBusyIds(new Set([...gwBusyIds, g.id]));
      const { pingGateway, listGateways } = await import(
        "../../lib/api/networking.js"
      );
      await pingGateway(g.id, { count: 3, timeoutMs: 800 });
      const gs = await listGateways();
      (gs.items || []).forEach((x) => dispatch({ type: "GW_ADD", gateway: x }));
    } catch {}
    setGwBusyIds((prev) => {
      const cp = new Set(prev);
      cp.delete(g.id);
      return cp;
    });
  };
  const tcpGw = async (g) => {
    try {
      setGwBusyIds(new Set([...gwBusyIds, g.id]));
      const { tcpGateway, listGateways } = await import(
        "../../lib/api/networking.js"
      );
      await tcpGateway(g.id, {
        ports: g.ports && g.ports.length ? g.ports : [502, 4840],
      });
      const gs = await listGateways();
      (gs.items || []).forEach((x) => dispatch({ type: "GW_ADD", gateway: x }));
    } catch {}
    setGwBusyIds((prev) => {
      const cp = new Set(prev);
      cp.delete(g.id);
      return cp;
    });
  };
  const useInAddDevice = (g) => {
    setLeft("connect");
    const common =
      (g.ports && g.ports[0]) || (g.protocol_hint === "opcua" ? 4840 : 502);
    setProto(g.protocol_hint === "opcua" ? "opcua" : "modbus");
    setFb((prev) => ({ ...prev, host: g.host, port: common }));
    setUa((prev) => ({
      ...prev,
      endpoint:
        g.protocol_hint === "opcua"
          ? `opc.tcp://${g.host}:${common}`
          : prev.endpoint,
    }));
  };
  const saveGwEdit = async (g) => {
    try {
      const { updateGateway } = await import("../../lib/api/networking.js");
      const payload = {
        name: gwDraft.name,
        host: gwDraft.host,
        ports: gwDraft.ports,
        protocol_hint: gwDraft.protocol_hint,
        nic_hint: gwDraft.nic_hint,
      };
      const res = await updateGateway(g.id, payload);
      if (res?.item) dispatch({ type: "GW_ADD", gateway: res.item });
      setGwEditingId(null);
    } catch {}
  };
  const duplicateGw = async (g) => {
    try {
      const { addGateway } = await import("../../lib/api/networking.js");
      const res = await addGateway({
        name: `${g.name} (copy)`,
        host: g.host,
        ports: g.ports || [],
        protocol_hint: g.protocol_hint,
        nic_hint: g.nic_hint,
      });
      if (res?.item) dispatch({ type: "GW_ADD", gateway: res.item });
    } catch {}
  };

  // Connect (Add Device) local state
  const [adding, setAdding] = useState(false);
  const [proto, setProto] = useState("modbus"); // 'modbus' | 'opcua'
  const [fb, setFb] = useState({
    host: "",
    port: 502,
    unitId: 1,
    mode: "network",
    com: "COM3",
    baud: 9600,
    parity: "N",
    stop: 1,
    timeoutMs: 1000,
    retries: 1,
    endian: "be",
  });
  const [ua, setUa] = useState({
    endpoint: "",
    auth: "anon",
    user: "",
    pass: "",
  });
  const [probe, setProbe] = useState(null); // { ok, value, latency }
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [saveName, setSaveName] = useState("Device-1");
  const [devMsg, setDevMsg] = useState("");
  const [devMsgOk, setDevMsgOk] = useState(false);

  const [testing, setTesting] = useState(false);
  const doTest = async () => {
    setProbe(null);
    setTesting(true);
    try {
      if (proto === "modbus") {
        const { testModbus } = await import("../../lib/api/networking.js");
        const t0 = performance.now();
        const res = await testModbus({
          host: fb.host,
          port: fb.port,
          unitId: fb.unitId,
          timeoutMs: fb.timeoutMs,
        });
        const latency = Math.round(performance.now() - t0);
        setProbe({
          ok: !!res.ok,
          value: res.ok ? "TCP OK" : res.message || "Failed",
          latency,
        });
      } else {
        const { testOpcUa } = await import("../../lib/api/networking.js");
        let ep = (
          ua.endpoint || "opc.tcp://localhost:4840/freeopcua/server/"
        ).trim();
        if (ep.includes("0.0.0.0")) ep = ep.replace("0.0.0.0", "127.0.0.1");
        const t0 = performance.now();
        const res = await testOpcUa({ endpoint: ep });
        const latency = Math.round(performance.now() - t0);
        setProbe({
          ok: !!res.ok,
          value: res.ok
            ? res.value !== undefined
              ? String(res.value)
              : "Connect OK"
            : res.message || "Failed",
          latency,
        });
      }
    } catch (e) {
      console.error("Device test failed", e);
      setProbe({ ok: false, value: "Failed", latency: 0 });
    } finally {
      setTesting(false);
    }
  };

  const doConnect = async () => {
    setConnecting(true);
    try {
      if (!probe?.ok) {
        setConnected(false);
        return;
      }
      setConnected(true);
    } finally {
      setConnecting(false);
    }
  };

  const doSave = async () => {
    setDevMsg("");
    setDevMsgOk(false);
    const name = (saveName || "").trim();
    if (!connected || !probe?.ok) {
      setDevMsg("Please test successfully and connect before saving");
      return;
    }
    if (!name) {
      setDevMsg("Device name is required");
      return;
    }
    if (
      devices.some((d) => (d.name || "").toLowerCase() === name.toLowerCase())
    ) {
      setDevMsg("A device with this name already exists");
      return;
    }
    const params = proto === "modbus" ? fb : ua;
    try {
      const { createDevice } = await import("../../lib/api/networking.js");
      const res = await createDevice({
        name,
        protocol: proto,
        params,
        autoReconnect: true,
      });
      if (res && res.item) {
        if (
          devices.some(
            (d) =>
              d.id === res.item.id ||
              (d.name || "").toLowerCase() ===
                (res.item.name || "").toLowerCase()
          )
        ) {
          setDevMsg("Device already exists");
          setDevMsgOk(false);
        } else {
          dispatch({ type: "DEV_ADD", device: res.item });
          setDevMsg("Device saved");
          setDevMsgOk(true);
        }
      }
    } catch (e) {
      setDevMsg("Save failed");
      setDevMsgOk(false);
      return;
    }
    // Reset
    setAdding(false);
    setConnected(false);
    setProbe(null);
  };

  const quickTestDevice = async (id) => {
    dispatch({
      type: "DEV_UPDATE_STATUS",
      id,
      patch: { status: "connecting" },
    });
    const latency = Math.round(25 + Math.random() * 100);
    await new Promise((r) => setTimeout(r, latency));
    const ok = Math.random() > 0.1;
    dispatch({
      type: "DEV_UPDATE_STATUS",
      id,
      patch: {
        status: ok ? "connected" : "degraded",
        latencyMs: latency,
        lastError: ok ? null : "Intermittent response",
      },
    });
  };

  const toggleConn = async (d) => {
    if (d.status === "connected" || d.status === "degraded") {
      dispatch({
        type: "DEV_UPDATE_STATUS",
        id: d.id,
        patch: { status: "disconnected" },
      });
    } else {
      dispatch({
        type: "DEV_UPDATE_STATUS",
        id: d.id,
        patch: { status: "connecting" },
      });
      const latency = Math.round(30 + Math.random() * 150);
      await new Promise((r) => setTimeout(r, latency));
      dispatch({
        type: "DEV_UPDATE_STATUS",
        id: d.id,
        patch: { status: "connected", latencyMs: latency, lastError: null },
      });
    }
  };

  // Databases
  const [dbForm, setDbForm] = useState({
    provider: "sqlite",
    conn: "file:plc_logger.db",
  });
  const addTarget = async () => {
    const { addDbTarget, listTargets } = await import(
      "../../lib/api/networking.js"
    );
    await addDbTarget({ provider: dbForm.provider, conn: dbForm.conn });
    const res = await listTargets();
    dispatch({ type: "DB_SET_ALL", items: res.items || [] });
    if (res.defaultId) dispatch({ type: "DB_SET_DEFAULT", id: res.defaultId });
  };
  const testTarget = async (t) => {
    const { testDbTarget } = await import("../../lib/api/networking.js");
    dispatch({ type: "DB_MARK_TESTING", id: t.id });
    const r = await testDbTarget({ id: t.id });
    dispatch({
      type: "DB_UPDATE_TARGET",
      id: t.id,
      patch: {
        status: r.ok ? "ok" : "fail",
        lastMsg: r.message || (r.ok ? "OK" : "fail"),
      },
    });
  };
  const setDefault = async (id) => {
    const { setDefaultTarget } = await import("../../lib/api/networking.js");
    await setDefaultTarget(id);
    dispatch({ type: "DB_SET_DEFAULT", id });
  };

  useEffect(() => {
    (async () => {
      try {
        const { listTargets, listGateways, listDevices } = await import(
          "../../lib/api/networking.js"
        );
        const targetsRes = await listTargets();
        dispatch({ type: "DB_SET_ALL", items: targetsRes.items || [] });
        if (targetsRes.defaultId)
          dispatch({ type: "DB_SET_DEFAULT", id: targetsRes.defaultId });
        try {
          const gs = await listGateways();
          (gs.items || []).forEach((g) =>
            dispatch({ type: "GW_ADD", gateway: g })
          );
        } catch {}
        try {
          const devs = await listDevices();
          (devs.items || []).forEach((d) =>
            dispatch({ type: "DEV_ADD", device: d })
          );
        } catch {}
      } catch {}
    })();
  }, []);

  // Light polling to keep device statuses fresh (for auto-reconnect feedback)
  useEffect(() => {
    let timer = null;
    (async function poll() {
      try {
        const { listDevices } = await import("../../lib/api/networking.js");
        const devs = await listDevices();
        (devs.items || []).forEach((d) =>
          dispatch({ type: "DEV_ADD", device: d })
        );
      } catch {}
      timer = setTimeout(poll, 3000);
    })();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [dispatch]);

  // Left rail item component
  const LeftItem = ({ id, title, subtitle, badge, active, onClick }) => (
    <button
      id={id}
      className={`rail-item ${active ? "active" : ""}`}
      onClick={onClick}
      aria-current={active ? "true" : "false"}
    >
      <div className="rail-title">{title}</div>
      {subtitle && <div className="rail-sub">{subtitle}</div>}
      {badge}
    </button>
  );

  return (
    <div className="networking">
      <aside className="rail" aria-label="Networking sections">
        <LeftItem
          id="reachability"
          title="Reachability"
          subtitle={reach.target || "Check network & ports"}
          active={left === "reachability"}
          onClick={() => setLeft("reachability")}
          badge={
            reach.lastPing ? (
              <Dot status={reach.lastPing.success ? "ok" : "fail"} />
            ) : null
          }
        />
        <LeftItem
          id="gateways"
          title="Saved Gateways"
          subtitle={`${gateways.length} saved`}
          active={left === "gateways"}
          onClick={() => setLeft("gateways")}
        />
        <LeftItem
          id="connect"
          title="Connect"
          subtitle="Add Device"
          active={left === "connect"}
          onClick={() => setLeft("connect")}
        />
        <LeftItem
          id="devices"
          title="Saved Devices"
          subtitle={`${devices.length} saved`}
          active={left === "devices"}
          onClick={() => setLeft("devices")}
          badge={hasConnected ? <Dot status="connected" /> : null}
        />
        <LeftItem
          id="databases"
          title="Databases"
          subtitle={`${targets.length} targets`}
          active={left === "databases"}
          onClick={() => setLeft("databases")}
          badge={defaultOk ? <Dot status="ok" /> : null}
        />
      </aside>

      <main className="main" aria-live="polite">
        {left === "reachability" && (
          <section>
            <h3>Reachability</h3>
            <div className="row">
              <label>Adapter</label>
              <select
                value={reach.adapterId}
                onChange={(e) =>
                  dispatch({ type: "NET_SET_ADAPTER", id: e.target.value })
                }
              >
                {reach.adapters.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label} ({a.ip}/{a.cidr})
                  </option>
                ))}
              </select>
            </div>
            <div className="row">
              <label>Target address</label>
              <input
                value={reach.target}
                onChange={(e) =>
                  dispatch({ type: "NET_SET_TARGET", target: e.target.value })
                }
                placeholder="IP or host"
              />
              <span className="hint">{subnetHint}</span>
            </div>
            <div className="row">
              <button onClick={runPing} disabled={reach.isPinging}>
                {reach.isPinging ? "Pinging…" : "Ping"}
              </button>
              <button
                onClick={() => runPortTests([502, 4840, 80, 443])}
                disabled={reach.isPortTesting}
              >
                {reach.isPortTesting ? "Testing ports…" : "Test common ports"}
              </button>
            </div>
            {reach.lastPing && (
              <div className="card">
                <div>
                  <strong>Ping:</strong>{" "}
                  {reach.lastPing.success ? "OK" : "Failed"} | loss{" "}
                  {reach.lastPing.lossPct}% | min {reach.lastPing.min}ms avg{" "}
                  {reach.lastPing.avg}ms max {reach.lastPing.max}ms
                </div>
                <div className="samples">
                  {reach.lastPing.samples.map((s, i) => (
                    <span
                      key={i}
                      style={{
                        height: Math.max(4, Math.min(40, s)),
                        display: "inline-block",
                        width: 6,
                        background: "#cfe3ff",
                        marginRight: 2,
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
            {reach.lastPing?.success && (
              <div className="card">
                <strong>Save as gateway</strong>
                <div className="row">
                  <label>Name</label>
                  <input
                    value={
                      gwName || (reach.target ? `Gateway ${reach.target}` : "")
                    }
                    onChange={(e) => setGwName(e.target.value)}
                    placeholder="Gateway name"
                  />
                  <button
                    onClick={async () => {
                      try {
                        const { addGateway } = await import(
                          "../../lib/api/networking.js"
                        );
                        const name = (
                          gwName || `Gateway ${reach.target}`
                        ).trim();
                        const res = await addGateway({
                          name,
                          host: reach.target,
                          adapterId: reach.adapterId,
                        });
                        if (res?.item)
                          dispatch({ type: "GW_ADD", gateway: res.item });
                        setGwName("");
                      } catch (e) {}
                    }}
                  >
                    Save
                  </button>
                </div>
                {gateways.length > 0 && (
                  <div className="row">
                    <label>Saved</label>
                    <div>
                      {gateways.map((g) => (
                        <span key={g.id} style={{ marginRight: 8 }}>
                          {g.name} ({g.host}){" "}
                          <button
                            onClick={async () => {
                              try {
                                const { deleteGateway } = await import(
                                  "../../lib/api/networking.js"
                                );
                                await deleteGateway(g.id);
                                dispatch({ type: "GW_DELETE", id: g.id });
                              } catch (e) {}
                            }}
                            aria-label={`Remove ${g.name}`}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {reach.portTests?.length > 0 && (
              <div className="card">
                <strong>Ports:</strong>
                <div className="ports">
                  {reach.portTests.map((r) => (
                    <div key={r.port} className="port-pill">
                      <Dot
                        status={
                          r.status === "open"
                            ? "ok"
                            : r.status === "timeout"
                            ? "degraded"
                            : "fail"
                        }
                      />
                      <span>
                        {" "}
                        {r.port} - {r.status} - {r.timeMs}ms
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {left === "gateways" && (
          <section>
            <h3>Saved Gateways</h3>
            <div className="row">
              <button
                onClick={async () => {
                  const { listGateways } = await import(
                    "../../lib/api/networking.js"
                  );
                  const gs = await listGateways();
                  (gs.items || []).forEach((g) =>
                    dispatch({ type: "GW_ADD", gateway: g })
                  );
                }}
              >
                Refresh
              </button>
              <button
                onClick={async () => {
                  for (const g of gateways) await pingGw(g);
                }}
              >
                Ping All
              </button>
              <button
                onClick={async () => {
                  for (const g of gateways) await tcpGw(g);
                }}
              >
                Test All Ports
              </button>
            </div>
            <div className="card" style={{ marginTop: 12 }}>
              <div className="grid">
                <div className="row">
                  <label>Name</label>
                  <input
                    value={gwDraft.name}
                    onChange={(e) =>
                      setGwDraft({ ...gwDraft, name: e.target.value })
                    }
                  />
                  <label>Host</label>
                  <input
                    value={gwDraft.host}
                    onChange={(e) =>
                      setGwDraft({ ...gwDraft, host: e.target.value })
                    }
                    placeholder="IP or host"
                  />
                  <label>Ports</label>
                  <input
                    value={(gwDraft.ports || []).join(",")}
                    onChange={(e) =>
                      setGwDraft({
                        ...gwDraft,
                        ports: (e.target.value || "")
                          .split(",")
                          .map((s) => parseInt(s, 10))
                          .filter((n) => !Number.isNaN(n)),
                      })
                    }
                    placeholder="502,4840"
                  />
                  <label>Protocol</label>
                  <select
                    value={gwDraft.protocol_hint}
                    onChange={(e) =>
                      setGwDraft({ ...gwDraft, protocol_hint: e.target.value })
                    }
                  >
                    <option value="">(auto)</option>
                    <option value="modbus">Modbus</option>
                    <option value="opcua">OPC UA</option>
                    <option value="generic">Generic</option>
                  </select>
                  <button onClick={addGatewayQuick}>Add Gateway</button>
                </div>
              </div>
            </div>

            <div className="table" style={{ marginTop: 12 }}>
              <div className="row header">
                <div className="cell name">Name</div>
                <div className="cell proto">Host</div>
                <div className="cell lat">Ports</div>
                <div className="cell lat">Status</div>
                <div className="cell act">Actions</div>
              </div>
              {gateways.map((g) => {
                const editing = gwEditingId === g.id;
                const ports =
                  g.ports && g.ports.length ? g.ports.join(",") : "";
                const status =
                  g.status ||
                  ((Array.isArray(g.last_tcp) &&
                    g.last_tcp.some((r) => r.status === "open")) ||
                  g.last_ping?.ok
                    ? "reachable"
                    : "unknown");
                return (
                  <div key={g.id} className="row line">
                    <div className="cell name">
                      {editing ? (
                        <input
                          value={gwDraft.name}
                          onChange={(e) =>
                            setGwDraft({ ...gwDraft, name: e.target.value })
                          }
                        />
                      ) : (
                        <>{g.name}</>
                      )}
                    </div>
                    <div className="cell proto">
                      {editing ? (
                        <input
                          value={gwDraft.host}
                          onChange={(e) =>
                            setGwDraft({ ...gwDraft, host: e.target.value })
                          }
                        />
                      ) : (
                        <>{g.host}</>
                      )}
                    </div>
                    <div className="cell lat">
                      {editing ? (
                        <input
                          value={gwDraft.ports?.join(",") || ""}
                          onChange={(e) =>
                            setGwDraft({
                              ...gwDraft,
                              ports: (e.target.value || "")
                                .split(",")
                                .map((s) => parseInt(s, 10))
                                .filter((n) => !Number.isNaN(n)),
                            })
                          }
                        />
                      ) : (
                        <>{ports}</>
                      )}
                    </div>
                    <div className="cell lat">
                      <Dot
                        status={
                          status === "reachable"
                            ? "ok"
                            : status === "limited"
                            ? "degraded"
                            : status === "unreachable"
                            ? "fail"
                            : "connecting"
                        }
                      />{" "}
                      {status}
                    </div>
                    <div className="cell act">
                      {!editing && (
                        <>
                          <button
                            onClick={() => pingGw(g)}
                            disabled={gwBusyIds.has(g.id)}
                          >
                            Ping
                          </button>
                          <button
                            onClick={() => tcpGw(g)}
                            disabled={gwBusyIds.has(g.id)}
                          >
                            TCP Test
                          </button>
                          <button onClick={() => useInAddDevice(g)}>
                            Use in Add Device
                          </button>
                          <button
                            onClick={() => {
                              setGwEditingId(g.id);
                              setGwDraft({
                                name: g.name,
                                host: g.host,
                                ports: g.ports || [],
                                protocol_hint: g.protocol_hint || "",
                                nic_hint: g.nic_hint || "",
                              });
                            }}
                          >
                            Edit
                          </button>
                          <button onClick={() => duplicateGw(g)}>
                            Duplicate
                          </button>
                          <button
                            onClick={async () => {
                              try {
                                await navigator.clipboard?.writeText(
                                  JSON.stringify(g)
                                );
                              } catch {}
                            }}
                          >
                            Export
                          </button>
                          <button
                            onClick={async () => {
                              if (!confirm(`Delete ${g.name}?`)) return;
                              try {
                                const { deleteGateway } = await import(
                                  "../../lib/api/networking.js"
                                );
                                await deleteGateway(g.id);
                                dispatch({ type: "GW_DELETE", id: g.id });
                              } catch {}
                            }}
                          >
                            Delete
                          </button>
                        </>
                      )}
                      {editing && (
                        <>
                          <button onClick={() => saveGwEdit(g)}>Save</button>
                          <button onClick={() => setGwEditingId(null)}>
                            Cancel
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {left === "connect" && (
          <section>
            <h3>Connect</h3>
            {!adding && (
              <button
                onClick={() => {
                  setAdding(true);
                  setConnected(false);
                  setProbe(null);
                }}
              >
                Add Device
              </button>
            )}
            {adding && (
              <div className="card">
                <div className="row">
                  <label>Protocol</label>
                  <select
                    value={proto}
                    onChange={(e) => setProto(e.target.value)}
                  >
                    <option value="modbus">Modbus</option>
                    <option value="opcua">OPC UA</option>
                  </select>
                </div>
                {proto === "modbus" ? (
                  <>
                    <div className="grid">
                      <div className="row">
                        <label>Gateway</label>
                        <select
                          value={fb.host}
                          onChange={(e) =>
                            setFb({ ...fb, host: e.target.value })
                          }
                        >
                          <option value="">(manual)</option>
                          {gateways.map((g) => (
                            <option key={g.id} value={g.host}>
                              {g.name} ({g.host})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="row">
                        <label>Address</label>
                        <input
                          value={fb.host}
                          onChange={(e) =>
                            setFb({ ...fb, host: e.target.value })
                          }
                          placeholder="IP or host"
                        />
                      </div>
                      <div className="row">
                        <label>Port</label>
                        <input
                          type="number"
                          value={fb.port}
                          onChange={(e) =>
                            setFb({ ...fb, port: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="row">
                        <label>Unit ID</label>
                        <input
                          type="number"
                          value={fb.unitId}
                          onChange={(e) =>
                            setFb({ ...fb, unitId: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="row">
                        <label>Mode</label>
                        <select
                          value={fb.mode}
                          onChange={(e) =>
                            setFb({ ...fb, mode: e.target.value })
                          }
                        >
                          <option value="network">Network</option>
                          <option value="serial">Serial</option>
                        </select>
                      </div>
                      {fb.mode === "serial" && (
                        <>
                          <div className="row">
                            <label>COM</label>
                            <input
                              value={fb.com}
                              onChange={(e) =>
                                setFb({ ...fb, com: e.target.value })
                              }
                            />
                          </div>
                          <div className="row">
                            <label>Baud</label>
                            <input
                              type="number"
                              value={fb.baud}
                              onChange={(e) =>
                                setFb({ ...fb, baud: Number(e.target.value) })
                              }
                            />
                          </div>
                          <div className="row">
                            <label>Parity</label>
                            <input
                              value={fb.parity}
                              onChange={(e) =>
                                setFb({ ...fb, parity: e.target.value })
                              }
                            />
                          </div>
                          <div className="row">
                            <label>Stop bits</label>
                            <input
                              type="number"
                              value={fb.stop}
                              onChange={(e) =>
                                setFb({ ...fb, stop: Number(e.target.value) })
                              }
                            />
                          </div>
                        </>
                      )}
                      <div className="row">
                        <label>Timeout (ms)</label>
                        <input
                          type="number"
                          value={fb.timeoutMs}
                          onChange={(e) =>
                            setFb({ ...fb, timeoutMs: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="row">
                        <label>Retries</label>
                        <input
                          type="number"
                          value={fb.retries}
                          onChange={(e) =>
                            setFb({ ...fb, retries: Number(e.target.value) })
                          }
                        />
                      </div>
                    </div>
                    <details className="adv">
                      <summary>Advanced</summary>
                      <div className="row">
                        <label>Endianness</label>
                        <select
                          value={fb.endian}
                          onChange={(e) =>
                            setFb({ ...fb, endian: e.target.value })
                          }
                        >
                          <option value="be">Big-endian</option>
                          <option value="le">Little-endian</option>
                        </select>
                      </div>
                    </details>
                  </>
                ) : (
                  <>
                    <div className="grid">
                      <div className="row">
                        <label>Endpoint</label>
                        <input
                          value={ua.endpoint}
                          onChange={(e) =>
                            setUa({ ...ua, endpoint: e.target.value })
                          }
                        />
                      </div>
                      <div className="row">
                        <label>Auth</label>
                        <select
                          value={ua.auth}
                          onChange={(e) =>
                            setUa({ ...ua, auth: e.target.value })
                          }
                        >
                          <option value="anon">Anonymous</option>
                          <option value="user">User/Password</option>
                        </select>
                      </div>
                      {ua.auth === "user" && (
                        <>
                          <div className="row">
                            <label>User</label>
                            <input
                              value={ua.user}
                              onChange={(e) =>
                                setUa({ ...ua, user: e.target.value })
                              }
                            />
                          </div>
                          <div className="row">
                            <label>Password</label>
                            <input
                              type="password"
                              value={ua.pass}
                              onChange={(e) =>
                                setUa({ ...ua, pass: e.target.value })
                              }
                            />
                          </div>
                        </>
                      )}
                    </div>
                  </>
                )}
                <div className="row">
                  <button onClick={doTest} disabled={testing}>
                    {testing ? "Testing…" : "Test"}
                  </button>
                  <button
                    onClick={doConnect}
                    disabled={connecting || connected}
                  >
                    {connecting
                      ? "Connecting…"
                      : connected
                      ? "Connected"
                      : "Connect"}
                  </button>
                  <button
                    onClick={() => {
                      setAdding(false);
                      setConnected(false);
                      setProbe(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
                {probe && (
                  <div className="card">
                    {probe.ok ? "Test OK" : "Test failed"} • {probe.latency}ms
                  </div>
                )}
                {connected && (
                  <div className="row">
                    <label>Device name</label>
                    <input
                      value={saveName}
                      onChange={(e) => setSaveName(e.target.value)}
                    />
                    <button onClick={doSave}>Save Device</button>
                  </div>
                )}
                {devMsg && (
                  <div
                    className="hint"
                    style={{ color: devMsgOk ? "#22a06b" : "#ef4444" }}
                  >
                    {devMsg}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {left === "devices" && (
          <section>
            <h3>Saved Devices</h3>
            {devices.length === 0 && <div>No devices saved yet.</div>}
            {devices.length > 0 && (
              <div className="table">
                {devices.map((d) => (
                  <div
                    key={d.id}
                    className={`row line ${
                      selectedDeviceId === d.id ? "sel" : ""
                    }`}
                    onClick={() => setSelectedDeviceId(d.id)}
                  >
                    <div className="cell name">
                      <Dot status={d.status} /> {d.name}
                    </div>
                    <div className="cell proto">{d.protocol}</div>
                    <div className="cell lat">
                      {d.latencyMs ? `${d.latencyMs}ms` : "—"}
                    </div>
                    <div className="cell act">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleConn(d);
                        }}
                      >
                        {d.status === "connected" || d.status === "degraded"
                          ? "Disconnect"
                          : "Connect"}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          quickTestDevice(d.id);
                        }}
                      >
                        Quick Test
                      </button>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          try {
                            const { request } = await import(
                              "../../lib/api/client.js"
                            );
                            await request(`/devices/${d.id}`, {
                              method: "DELETE",
                            });
                            dispatch({ type: "DEV_DELETE", id: d.id });
                          } catch (err) {
                            /* ignore */
                          }
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {selectedDeviceId && (
              <div className="card" style={{ marginTop: 12 }}>
                <strong>Device details</strong>
                <div>
                  Latency:{" "}
                  {devices.find((d) => d.id === selectedDeviceId)?.latencyMs ??
                    "—"}{" "}
                  ms
                </div>
                <div>
                  Status:{" "}
                  {devices.find((d) => d.id === selectedDeviceId)?.status}
                </div>
                {devices.find((d) => d.id === selectedDeviceId)?.lastError && (
                  <div style={{ color: "#ef4444" }}>
                    Last error:{" "}
                    {devices.find((d) => d.id === selectedDeviceId)?.lastError}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {left === "databases" && (
          <section>
            <h3>Databases</h3>
            <div className="grid">
              <div className="row">
                <label>Provider</label>
                <select
                  value={dbForm.provider}
                  onChange={(e) =>
                    setDbForm({ ...dbForm, provider: e.target.value })
                  }
                >
                  <option value="sqlite">SQLite</option>
                  <option value="postgres">Postgres</option>
                  <option value="sqlserver">SQL Server</option>
                  <option value="mysql">MySQL</option>
                </select>
              </div>
              <div className="row">
                <label>Connection</label>
                <input
                  value={dbForm.conn}
                  onChange={(e) =>
                    setDbForm({ ...dbForm, conn: e.target.value })
                  }
                  placeholder="connection string or file path"
                />
              </div>
              <div className="row">
                <button onClick={addTarget}>Add Target</button>
              </div>
            </div>
            <div className="table" style={{ marginTop: 12 }}>
              {targets.map((t) => (
                <div key={t.id} className="row line">
                  <div className="cell name">
                    <Dot
                      status={
                        t.status === "ok"
                          ? "ok"
                          : t.status === "fail"
                          ? "fail"
                          : "connecting"
                      }
                    />{" "}
                    {t.provider} • {t.conn}
                  </div>
                  <div className="cell act">
                    <button
                      onClick={() => testTarget(t)}
                      disabled={t.status === "testing"}
                    >
                      {t.status === "testing" ? "Testing…" : "Test"}
                    </button>
                    <button
                      disabled={t.status !== "ok"}
                      onClick={() => setDefault(t.id)}
                    >
                      {defaultTargetId === t.id ? "Default" : "Set Default"}
                    </button>
                    <button
                      onClick={async () => {
                        if (
                          !confirm(
                            "Delete this target? This only removes it from the app."
                          )
                        )
                          return;
                        try {
                          const { deleteDbTarget } = await import(
                            "../../lib/api/networking.js"
                          );
                          await deleteDbTarget(t.id);
                          dispatch({ type: "DB_DELETE_TARGET", id: t.id });
                        } catch (e) {
                          const body = e?.body || e?.message || "";
                          if (String(body).includes("TARGET_IS_DEFAULT"))
                            alert(
                              "Cannot delete Default target. Set another Default first."
                            );
                          else if (String(body).includes("TARGET_IN_USE"))
                            alert(
                              "Target in use by logical tables. Reassign or remove them first."
                            );
                          else alert("Delete failed");
                        }
                      }}
                    >
                      Delete
                    </button>
                    {defaultTargetId === t.id && (
                      <span style={{ marginLeft: 8 }}>★ Default</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="gate">
          <div className="checks">
            <div>
              <Dot status={hasConnected ? "ok" : "fail"} /> At least one device
              is connected
            </div>
            <div>
              <Dot status={defaultOk ? "ok" : "fail"} /> A database target is
              test-OK and set as default
            </div>
          </div>
          {hasConnected && defaultOk ? (
            <button onClick={() => onProceed && onProceed()}>
              Proceed to next
            </button>
          ) : (
            <div className="hint">
              Complete the unmet items above to proceed.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
