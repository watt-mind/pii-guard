// The Scalar renderer, in its own chunk: only #api downloads it (LAB-1586).
import "@scalar/api-reference-react/style.css";
import "./apiReference.theme.css";
import "./scalar-toasts.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiReferenceReact } from "@scalar/api-reference-react";
import { hostedSpec, referenceConfig, type ApiServer } from "./apiConfig";

export default function ScalarReference({ specUrl, dark, servers, endpoint = null }: { specUrl: string; dark: boolean; servers?: ApiServer[]; endpoint?: string | null }) {
  // In the console the spec is read once and rewritten for this service (LAB-1626).
  const [content, setContent] = useState<object | null>(null);
  useEffect(() => {
    if (!servers) return;
    let live = true;
    fetch(specUrl)
      .then((r) => r.json())
      .then((spec: object) => live && setContent(hostedSpec(spec, globalThis.location?.origin ?? "", endpoint)))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [specUrl, servers, endpoint]);
  const configuration = useMemo(() => referenceConfig(specUrl, dark, servers, content ?? undefined), [specUrl, dark, servers, content]);
  const frame = useRef<HTMLDivElement>(null);
  // Scalar renders its content as a <main>; inside the page's own <main> that is a second main
  // landmark (axe). It stays a named region instead (LAB-1629), re-applied when Scalar re-renders.
  useEffect(() => {
    const root = frame.current;
    if (!root) return;
    const demote = () => root.querySelectorAll("main").forEach((el) => el.getAttribute("role") !== "region" && el.setAttribute("role", "region"));
    demote();
    const observer = new MutationObserver(demote);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [content]);
  if (servers && !content) return <p role="status" className="mx-auto max-w-[1280px] px-4 py-6 text-muted sm:px-6 lg:px-10">Loading the reference…</p>;
  return (
    <div ref={frame}>
      <ApiReferenceReact configuration={configuration} />
    </div>
  );
}
