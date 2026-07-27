import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoadingScreen } from "./LoadingScreen";

describe("LoadingScreen", () => {
  it("shows the connecting message", () => {
    render(<LoadingScreen />);
    expect(screen.getByText(/Connecting to Interview Tracker/)).toBeInTheDocument();
  });
});
