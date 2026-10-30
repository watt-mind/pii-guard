// The Scalar renderer, in its own chunk: only #api downloads it (LAB-1586).
import "@scalar/api-reference-react/style.css";
import "./apiReference.theme.css";
import "./scalar-toasts.css";
import { useEffect, useMemo, useState } from "react";
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
  if (servers && !content) return <p role="status" className="mx-auto max-w-[1280px] px-4 py-6 text-muted sm:px-6 lg:px-10">Loading the reference…</p>;
  return <ApiReferenceReact configuration={configuration} />;
}
