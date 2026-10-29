import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./index.css";
import { StrictMode, type ComponentType } from "react";
import { createRoot } from "react-dom/client";

// Hosted deployment is an explicit build choice. Its public landing loads without the console,
// which HostedRoot fetches only for a signed-in owner (LAB-1450); the local build is the console.
const root: Promise<ComponentType> =
  import.meta.env.VITE_PII_GUARD_HOSTED === "true"
    ? import("./hosted/HostedRoot").then((m) => m.HostedRoot)
    : import("./App").then((m) => m.App);

void root.then((Root) =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <Root />
    </StrictMode>,
  ),
);
