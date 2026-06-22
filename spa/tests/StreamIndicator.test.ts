import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import StreamIndicator from "../src/lib/StreamIndicator.svelte";

describe("StreamIndicator", () => {
  it("shows 'Live' when connected", () => {
    render(StreamIndicator, { props: { status: "connected" } });
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("shows 'Connecting…' when connecting", () => {
    render(StreamIndicator, { props: { status: "connecting" } });
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("shows 'Reconnecting…' when reconnecting", () => {
    render(StreamIndicator, { props: { status: "reconnecting" } });
    expect(screen.getByText("Reconnecting…")).toBeInTheDocument();
  });

  it("shows 'Offline' when disconnected", () => {
    render(StreamIndicator, { props: { status: "disconnected" } });
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("has connected CSS class when status is connected", () => {
    const { container } = render(StreamIndicator, { props: { status: "connected" } });
    const indicator = container.querySelector(".stream-indicator");
    expect(indicator?.className).toContain("connected");
  });

  it("has disconnected CSS class when status is disconnected", () => {
    const { container } = render(StreamIndicator, { props: { status: "disconnected" } });
    const indicator = container.querySelector(".stream-indicator");
    expect(indicator?.className).toContain("disconnected");
  });
});
