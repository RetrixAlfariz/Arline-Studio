import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { StartupErrorBoundary } from "./StartupErrorBoundary";
import "./theme.css";
import "./styles.css";

document.documentElement.dataset.arlineUi = "react";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StartupErrorBoundary><App /></StartupErrorBoundary>
  </StrictMode>,
);
