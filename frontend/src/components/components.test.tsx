import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import { ScanActivity } from "./ScanActivity";
import { SettingsPage } from "./SettingsPage";
import { ThemeButton } from "./ThemeButton";
import { sampleInterviews } from "../fixtures/interviews";
import { failedScan, runningScheduledScan } from "../fixtures/scanStatus";
import { Toasts } from "./Toasts";

describe("Dashboard", () => {
  it("filters, paginates, and clears controls", () => {
    const onScan = vi.fn();
    const records = Array.from({ length: 12 }, (_, index) => ({
      ...sampleInterviews[0],
      thread_id: `t-${index}`,
      company: index % 2 === 0 ? "Even Co" : "Odd Co",
    }));
    render(
      <Dashboard records={records} generatedAt="now" connected onScan={onScan} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Scan Gmail now" }));
    expect(onScan).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "Odd" } });
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "5" } });
    expect(screen.getByText(/1 \/ 3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Phone Screen,/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
  });
});

describe("SettingsPage", () => {
  it("saves settings and surfaces errors", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ email: "ok@test.com", scan_times: ["09:00"], max_scan_times: 5 });
    render(
      <SettingsPage
        connected
        settings={{ email: "", scan_times: ["09:00"], max_scan_times: 5 }}
        save={save}
      />,
    );
    fireEvent.change(screen.getByLabelText("Email filter"), { target: { value: "a@test.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and apply schedule" }));
    expect(await screen.findByText("network down")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save and apply schedule" }));
    await waitFor(() => expect(screen.getByText(/Saved/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Add time" }));
  });
});

describe("ScanActivity", () => {
  it("shows failed scan details and minimized chip", () => {
    const setOpen = vi.fn();
    const { container, rerender } = render(
      <ScanActivity scan={failedScan} open setOpen={setOpen} />,
    );
    expect(screen.getByText(/Claude extraction failed/)).toBeInTheDocument();
    fireEvent.mouseDown(container.querySelector(".modal-backdrop")!);
    rerender(<ScanActivity scan={runningScheduledScan} open={false} setOpen={setOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /2\/5|Scanning/ }));
    expect(setOpen).toHaveBeenCalledWith(true);
    rerender(
      <ScanActivity
        scan={{ ...runningScheduledScan, total: 0, phase: "discovery", current: 0 }}
        open
        setOpen={setOpen}
      />,
    );
    expect(screen.getByText("0 of 0 threads")).toBeInTheDocument();
  });
});

describe("ThemeButton", () => {
  it("toggles theme preference", () => {
    localStorage.clear();
    render(<ThemeButton />);
    fireEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("Toasts", () => {
  it("dismisses on click", () => {
    const dismiss = vi.fn();
    render(<Toasts items={[{ id: "1", text: "Hello", kind: "info" }]} dismiss={dismiss} />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss notification/ }));
    expect(dismiss).toHaveBeenCalledWith("1");
  });
});
