import { Component, lazy, Suspense, type ReactNode } from "react";
import { Button, Notice } from "../components/ui";

const ImageShowcase = lazy(() => import("./ImageShowcase"));

/** A failed optional recording must not take away the shell or the text draft. */
class ImageExampleBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <Notice tone="warn" title="The recorded image example could not be loaded">
      <p>You can still use the <a className="underline underline-offset-4" href="#run">text walkthrough</a>.</p>
      <p className="mt-2">Reloading tries the download again and clears unsaved drafts.</p>
      <Button className="mt-3" onClick={() => window.location.reload()}>Reload page</Button>
    </Notice>;
    return this.props.children;
  }
}

export function RecordedImageExample() {
  return <ImageExampleBoundary><Suspense fallback={<p role="status" className="min-h-[420px] rounded-xl border border-line bg-surface p-5 text-muted">Loading the recorded image example…</p>}><ImageShowcase /></Suspense></ImageExampleBoundary>;
}
