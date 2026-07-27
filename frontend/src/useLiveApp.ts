import { useCallback, useEffect, useRef, useState } from "react";
import type { AppSnapshot, DashboardPayload, ScanStatus, ServerMessage, Settings } from "./types";

type Toast = { id: string; text: string; kind: "info" | "success" | "error" };

const idleScan: ScanStatus = { state: "idle", phase: "idle", current: 0, total: null };

export function useLiveApp() {
  const [snapshot, setSnapshot] = useState<AppSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const socket = useRef<WebSocket | null>(null);
  const retry = useRef(0);
  const reconnectTimer = useRef<number | undefined>(undefined);
  const previousRun = useRef<string | null>(null);
  const pending = useRef(new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>());

  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = crypto.randomUUID();
    setToasts((items) => [...items, { id, text, kind }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5000);
  }, []);

  const applyScan = useCallback((scan: ScanStatus) => {
    setSnapshot((current) => current ? { ...current, scan } : current);
    if (scan.state === "running" && scan.source === "scheduled" && previousRun.current !== scan.run_id) {
      toast("Scheduled scan is active and reading Gmail.", "info");
    }
    if (scan.state === "succeeded" && previousRun.current === scan.run_id) {
      toast("Scan complete. Dashboard updated.", "success");
    }
    if (scan.state === "failed" && previousRun.current === scan.run_id) {
      toast(scan.error || "Scan failed.", "error");
    }
    previousRun.current = scan.run_id || null;
  }, [toast]);

  const handleMessage = useCallback((message: ServerMessage) => {
    if (message.request_id && pending.current.has(message.request_id)) {
      const waiter = pending.current.get(message.request_id)!;
      pending.current.delete(message.request_id);
      if (message.type === "error") waiter.reject(new Error(String((message.payload as { error?: string }).error || "Request failed")));
      else waiter.resolve(message.payload);
    }
    if (message.type === "app.snapshot") {
      const next = message.payload as AppSnapshot;
      setSnapshot(next);
      applyScan(next.scan);
    } else if (message.type.startsWith("scan.")) {
      applyScan(message.payload as ScanStatus);
    } else if (message.type === "dashboard.updated") {
      setSnapshot((current) => current ? { ...current, dashboard: message.payload as DashboardPayload } : current);
    } else if (message.type === "settings.updated") {
      setSnapshot((current) => current ? { ...current, settings: message.payload as Settings } : current);
    }
  }, [applyScan]);

  useEffect(() => {
    let disposed = false;
    const connect = () => {
      if (disposed) return;
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${location.host}/ws`);
      socket.current = ws;
      ws.onopen = () => {
        retry.current = 0;
        setConnected(true);
        ws.send(JSON.stringify({ version: 1, type: "snapshot.request", request_id: crypto.randomUUID(), payload: {} }));
      };
      ws.onmessage = (event) => {
        try { handleMessage(JSON.parse(event.data) as ServerMessage); } catch { /* ignore malformed events */ }
      };
      ws.onclose = () => {
        setConnected(false);
        pending.current.forEach(({ reject }) => reject(new Error("Connection lost")));
        pending.current.clear();
        if (!disposed) {
          const delay = Math.min(15000, 500 * 2 ** retry.current++);
          reconnectTimer.current = window.setTimeout(connect, delay);
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      socket.current?.close();
    };
  }, [handleMessage]);

  const command = useCallback(<T,>(type: string, payload: unknown): Promise<T> => {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return Promise.reject(new Error("Live connection is offline"));
    const request_id = crypto.randomUUID();
    return new Promise<T>((resolve, reject) => {
      pending.current.set(request_id, { resolve: resolve as (value: unknown) => void, reject });
      ws.send(JSON.stringify({ version: 1, type, request_id, payload }));
      window.setTimeout(() => {
        if (pending.current.delete(request_id)) reject(new Error("Request timed out"));
      }, 15000);
    });
  }, []);

  return {
    snapshot,
    scan: snapshot?.scan || idleScan,
    connected,
    toasts,
    dismissToast: (id: string) => setToasts((items) => items.filter((item) => item.id !== id)),
    startScan: async () => {
      try {
        return await command<ScanStatus>("scan.start", {});
      } catch (error) {
        toast(error instanceof Error ? error.message : String(error), "error");
        throw error;
      }
    },
    saveSettings: (settings: Pick<Settings, "email" | "scan_times">) => command<Settings>("settings.save", settings),
  };
}
