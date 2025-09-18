import React, { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { Provider } from "./state/store.jsx";
import { setupClickLogging } from "./lib/frontlog.js";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element #root not found");
}

if (import.meta.env?.PROD) {
  setupClickLogging();
}

const root = createRoot(container);
root.render(
  <StrictMode>
    <Provider>
      <App />
    </Provider>
  </StrictMode>
);
