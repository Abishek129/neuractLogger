import React, { useState } from "react";
import * as api from "../../lib/api/equipment.js";

export function SignIn({ onSignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (ev) => {
    ev.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(username.trim(), password);
      onSignedIn();
    } catch (e) {
      setError(e.status === 401 ? "Wrong username or password" : api.errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="eq-signin eq-panel" onSubmit={submit}>
      <h3>Sign in</h3>
      <p className="eq-muted">The equipment API needs a Keycloak account with the logger-read / logger-write roles.</p>
      <label className="eq-field">
        <span>Username</span>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
      </label>
      <label className="eq-field">
        <span>Password</span>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </label>
      {error && <div className="eq-error">{error}</div>}
      <button className="eq-btn primary" disabled={busy || !username || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
