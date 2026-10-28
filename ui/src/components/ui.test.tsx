// The canonical components (LAB-1441): focus, announcements and native semantics.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button, Checkbox, ConfirmAction, Field, Input, Metric, Notice, SecretReveal, SegmentedControl } from "./ui";

describe("Button", () => {
  it("stays focusable while busy and ignores clicks", async () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Mask document
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Mask document" });
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    button.focus();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(button).toHaveFocus();
  });

  it("styles the danger variant as destructive", () => {
    render(<Button variant="danger">Drop session</Button>);
    expect(screen.getByRole("button", { name: "Drop session" }).className).toContain("text-danger");
  });
});

describe("Field", () => {
  it("links the hint and error as the description, not the name, and marks required", () => {
    render(
      <Field label="Endpoint name" hint="Shown in logs." error="Name is taken." required>
        <Input />
      </Field>,
    );
    const input = screen.getByRole("textbox", { name: "Endpoint name" });
    expect(input).toBeRequired();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Name is taken. Shown in logs.");
  });
});

describe("Checkbox", () => {
  it("is a native checkbox with its label", async () => {
    const onChange = vi.fn();
    render(<Checkbox label="Apply v2 to this endpoint" onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Apply v2 to this endpoint" }));
    expect(onChange).toHaveBeenCalled();
  });
});

describe("SegmentedControl", () => {
  function Theme() {
    const [value, setValue] = useState<"light" | "dark" | "system">("light");
    return (
      <SegmentedControl
        label="Theme"
        value={value}
        onChange={setValue}
        options={[
          { value: "light", label: "Light" },
          { value: "system", label: "System" },
          { value: "dark", label: "Dark" },
        ]}
      />
    );
  }

  it("is a radio group with one tab stop and arrow keys", async () => {
    render(<Theme />);
    const group = screen.getByRole("radiogroup", { name: "Theme" });
    expect(group).toBeInTheDocument();
    const light = screen.getByRole("radio", { name: "Light" });
    expect(light).toBeChecked();
    light.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
  });
});

describe("ConfirmAction", () => {
  it("asks first, focuses the danger button, and Cancel returns focus to the trigger", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmAction trigger="Revoke" triggerLabel="Revoke key production" title="Revoke key 'production'?" body="Apps using it stop working." confirm="Revoke key" onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke key production" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Revoke key 'production'?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke key" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Revoke key production" })).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("Escape cancels; confirming runs the action", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmAction trigger="Disconnect" title="Disconnect openai?" confirm="Disconnect provider" onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Disconnect" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await userEvent.click(screen.getByRole("button", { name: "Disconnect provider" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("Notice", () => {
  it("is a polite status when live and positive, an alert when live and negative", () => {
    const { rerender } = render(<Notice live tone="success">Endpoint created.</Notice>);
    expect(screen.getByRole("status")).toHaveTextContent("Endpoint created.");
    rerender(<Notice live tone="danger">Could not save.</Notice>);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save.");
  });
});

describe("SecretReveal", () => {
  it("is announced, focuses Copy, confirms on the button, and asks before dismissing an uncopied key", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<SecretReveal label="endpoint key ci" secret="pg_example_secret" onDismiss={onDismiss} />);
    expect(screen.getByRole("alert")).toHaveTextContent("shown only once");
    expect(screen.getByRole("button", { name: "Copy endpoint key ci" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Dismiss key" }));
    expect(onDismiss).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Keep showing" }));
    await user.click(screen.getByRole("button", { name: "Copy endpoint key ci" }));
    expect(await screen.findByRole("button", { name: "endpoint key ci copied" })).toHaveTextContent("Copied");
    await expect(navigator.clipboard.readText()).resolves.toBe("pg_example_secret");
    await user.click(screen.getByRole("button", { name: "Dismiss key" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe("Metric", () => {
  it("renders the label and value as a description pair", () => {
    render(
      <dl>
        <Metric label="Overhead" value="5.81" suffix="ms" />
      </dl>,
    );
    expect(screen.getByText("Overhead").tagName).toBe("DT");
    expect(screen.getByText("5.81").tagName).toBe("DD");
  });
});
