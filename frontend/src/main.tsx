import "leaflet/dist/leaflet.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";

// Keeps the map tiles you have viewed, for demos without internet (public/tile-cache-sw.js)
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/tile-cache-sw.js").catch(() => {});
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
