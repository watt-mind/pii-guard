// The Scalar renderer, in its own chunk: only #api downloads it (LAB-1586).
import "@scalar/api-reference-react/style.css";
import "./apiReference.theme.css";
import "./scalar-toasts.css";
import { useMemo } from "react";
import { ApiReferenceReact } from "@scalar/api-reference-react";
import { referenceConfig, type ApiServer } from "./apiConfig";

export default function ScalarReference({ specUrl, dark, servers }: { specUrl: string; dark: boolean; servers?: ApiServer[] }) {
  const configuration = useMemo(() => referenceConfig(specUrl, dark, servers), [specUrl, dark, servers]);
  return <ApiReferenceReact configuration={configuration} />;
}
