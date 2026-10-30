import { Component, type ReactNode } from "react";
import { Button, Notice } from "./ui";

/** A failed route download must not discard the shell or other views' drafts. */
export class PageLoadBoundary extends Component<{ children: ReactNode; reload?: () => void }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <Notice tone="danger" live title="This view could not be loaded.">
      <p>You can still use the other pages. Reload to try again; unsaved work will be cleared.</p>
      <Button onClick={() => this.props.reload ? this.props.reload() : window.location.reload()}>Reload page</Button>
    </Notice>;
  }
}
