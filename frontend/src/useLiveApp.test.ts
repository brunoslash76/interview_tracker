import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeSnapshot } from "./fixtures/appSnapshot";
import { runningScheduledScan } from "./fixtures/scanStatus";
import { WS_EVENTS } from "./fixtures/protocol";
import { FakeWebSocket, installFakeWebSocket } from "./test/fakeWebSocket";
import { useLiveApp } from "./useLiveApp";

describe("useLiveApp", () => {
  afterEach(() => {
    installFakeWebSocket({});
  });

  it("loads snapshot on connect and resolves commands", async () => {
    const snapshot = makeSnapshot();
    installFakeWebSocket({
      initialSnapshot: snapshot,
      autoReply: (message) => {
        FakeWebSocket.latest?.emit(
          WS_EVENTS.settingsUpdated,
          { email: "a@b.com", scan_times: ["08:00"], max_scan_times: 5 },
          message.request_id,
        );
      },
    });
    const { result } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    expect(result.current.connected).toBe(true);
    await act(async () => {
      const saved = await result.current.saveSettings({ email: "a@b.com", scan_times: ["08:00"] });
      expect(saved.email).toBe("a@b.com");
    });
  });

  it("rejects commands before the socket opens", async () => {
    installFakeWebSocket({ connectDelayMs: 60_000, initialSnapshot: makeSnapshot() });
    const { result, unmount } = renderHook(() => useLiveApp());
    await expect(result.current.startScan()).rejects.toThrow(/offline/i);
    unmount();
  });

  it("surfaces scan toasts once per scheduled run", async () => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot({ scan: runningScheduledScan }),
    });
    const { result } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    act(() => {
      FakeWebSocket.latest?.emit(WS_EVENTS.scanProgress, {
        ...runningScheduledScan,
        current: 2,
      });
    });
    expect(result.current.toasts.filter((t) => t.text.includes("Scheduled scan"))).toHaveLength(1);
  });

  it("handles scan.start errors from the server", async () => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot(),
      autoReply: (message) => {
        if (message.type === "scan.start" && message.request_id) {
          FakeWebSocket.latest?.emitError(message.request_id, "scan busy");
        }
      },
    });
    const { result, unmount } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.connected).toBe(true));
    await act(async () => {
      await expect(result.current.startScan()).rejects.toThrow();
    });
    unmount();
  });

  it("handles malformed websocket payloads and partial updates", async () => {
    installFakeWebSocket({ initialSnapshot: makeSnapshot() });
    const { result, unmount } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    act(() => {
      FakeWebSocket.latest?.onmessage?.({ data: "not-json" });
      FakeWebSocket.latest?.emit(WS_EVENTS.settingsUpdated, {
        email: "partial@test.com",
        scan_times: ["10:00"],
        max_scan_times: 5,
      });
    });
    await waitFor(() =>
      expect(result.current.snapshot?.settings.email).toBe("partial@test.com"),
    );
    unmount();
  });

  it("shows failed scan toast for the active run", async () => {
    installFakeWebSocket({
      initialSnapshot: makeSnapshot({
        scan: { ...runningScheduledScan, run_id: "fail-run" },
      }),
    });
    const { result } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    act(() => {
      FakeWebSocket.latest?.emit(WS_EVENTS.scanFailed, {
        ...runningScheduledScan,
        run_id: "fail-run",
        state: "failed",
        phase: "failed",
        error: "boom",
      });
    });
    expect(result.current.toasts.some((t) => t.text.includes("boom"))).toBe(true);
  });

  it("dismisses toasts manually", async () => {
    installFakeWebSocket({ initialSnapshot: makeSnapshot({ scan: runningScheduledScan }) });
    const { result } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.toasts.length).toBeGreaterThan(0));
    const id = result.current.toasts[0].id;
    act(() => result.current.dismissToast(id));
    expect(result.current.toasts.find((t) => t.id === id)).toBeUndefined();
  });

  it("times out pending commands", async () => {
    installFakeWebSocket({ initialSnapshot: makeSnapshot() });
    const { result, unmount } = renderHook(() => useLiveApp());
    await waitFor(() => expect(result.current.connected).toBe(true));
    vi.useFakeTimers();
    let caught: Error | undefined;
    const pending = result.current
      .saveSettings({ email: "slow@test.com", scan_times: [] })
      .catch((error: Error) => {
        caught = error;
      });
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await pending;
    });
    expect(caught?.message).toMatch(/timed out/i);
    vi.useRealTimers();
    unmount();
  });
});
