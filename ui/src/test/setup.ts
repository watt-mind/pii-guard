import { beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// jsdom doesn't implement scrolling.
window.scrollTo = () => {};
Element.prototype.scrollIntoView = () => {};

// The App keeps the open tab in the URL hash; start every test on the first tab.
beforeEach(() => {
  history.replaceState(null, "", "/");
});
