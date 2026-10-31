import { Component, type ReactNode } from "react";
import { errorCopy } from "../lib/errorCopy";
import { Button, Notice } from "./ui";

/** A failed route download must not discard the shell or other views' drafts. */
export class PageLoadBoundary extends Component<{ children: ReactNode; reload?: () => void }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const copy = errorCopy("page_load_failed");
    return <Notice tone="danger" live title={copy.title} data-error-kind={copy.kind}>
      <p>{copy.body}</p>
      <Button onClick={() => this.props.reload ? this.props.reload() : window.location.reload()}>Reload page</Button>
    </Notice>;
  }
}
