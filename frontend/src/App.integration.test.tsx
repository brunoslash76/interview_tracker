import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, beforeEach, it, expect } from "vitest";
import App from "./App";
import { makeSnapshot } from "./fixtures/appSnapshot";
import { idleScan, runningScheduledScan } from "./fixtures/scanStatus";
import { WS_EVENTS } from "./fixtures/protocol";
import { FakeWebSocket, installFakeWebSocket } from "./test/fakeWebSocket";

describe("App integration", () => {
  beforeEach(() => {
    history.replaceState({}, "", "/dashboard");
    sessionStorage.clear();
  });

  it("renders settings route", async () => {
    installFakeWebSocket({ initialSnapshot: makeSnapshot() });
    history.replaceState({}, "", "/settings");
    render(<App />);
    expect(await screen.findByLabelText("Email filter")).toBeInTheDocument();
  });

  it("opens scan modal for dashboard-initiated scans", async () => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot({ scan: idleScan }),
      autoReply: (message) => {
        if (message.type === WS_EVENTS.scanStartCommand && message.request_id) {
          FakeWebSocket.latest?.emit(
            WS_EVENTS.scanStarted,
            { ...runningScheduledScan, source: "dashboard", run_id: "dash-1" },
            message.request_id,
          );
        }
      },
    });
    render(<App />);
    await screen.findByText("Acme");
    fireEvent.click(screen.getByRole("button", { name: "Scan Gmail now" }));
    expect(await screen.findByRole("dialog", { name: "Gmail scan progress" })).toBeInTheDocument();
  });

  it("handles scan minimize, live dashboard, and completion", async () => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot({ scan: runningScheduledScan }),
    });
    render(<App />);
    expect(await screen.findByText(/Scheduled scan is active/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /2\/5/ }));
    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    act(() => {
      FakeWebSocket.latest?.emit(WS_EVENTS.dashboardUpdated, {
        records: [{ thread_id: "live", company: "Live Inc", stage: "Offer", status: "Active" }],
        generated_at: "live",
      });
    });
    expect(await screen.findByText("Live Inc")).toBeInTheDocument();
    act(() => {
      FakeWebSocket.latest?.emit(WS_EVENTS.scanCompleted, {
        ...runningScheduledScan,
        state: "succeeded",
        phase: "complete",
        current: 5,
      });
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
