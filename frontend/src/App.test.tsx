import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, it, expect } from "vitest";
import App from "./App";
import { makeSnapshot } from "./fixtures/appSnapshot";
import { runningScheduledScan } from "./fixtures/scanStatus";
import { FakeWebSocket, installFakeWebSocket } from "./test/fakeWebSocket";

describe("live scan UX", () => {
  beforeEach(() => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot({ scan: runningScheduledScan }),
    });
    history.replaceState({}, "", "/dashboard");
    sessionStorage.clear();
  });

  it("shows scheduled scans as a toast and minimizable activity", async () => {
    render(<App />);
    expect(await screen.findByText("Scheduled scan is active and reading Gmail.")).toBeInTheDocument();
    const activity = await screen.findByRole("button", { name: /2\/5/ });
    fireEvent.click(activity);
    expect(screen.getByRole("dialog", { name: "Gmail scan progress" })).toBeInTheDocument();
    expect(screen.getByText("2 of 5 threads")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("applies live dashboard updates and clears completed activity", async () => {
    render(<App />);
    await screen.findByText("Acme");
    act(() => {
      FakeWebSocket.latest?.emit("dashboard.updated", {
        records: [{ thread_id: "t2", company: "Bravo", stage: "Offer", status: "Offer Received" }],
        generated_at: "now",
      });
    });
    expect(await screen.findByText("Bravo")).toBeInTheDocument();
    act(() => {
      FakeWebSocket.latest?.emit("scan.completed", {
        ...runningScheduledScan,
        state: "succeeded",
        phase: "complete",
        current: 5,
      });
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: /5\/5/ })).not.toBeInTheDocument());
    expect(screen.getByText("Scan complete. Dashboard updated.")).toBeInTheDocument();
  });
});
