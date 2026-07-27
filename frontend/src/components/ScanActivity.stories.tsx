import type { Meta, StoryObj } from "@storybook/react";
import { userEvent, within } from "@storybook/test";
import { ScanActivity } from "./ScanActivity";
import { failedScan, runningScheduledScan } from "../fixtures/scanStatus";

const meta: Meta<typeof ScanActivity> = {
  title: "ScanActivity",
  component: ScanActivity,
  args: { open: true, setOpen: () => undefined },
};
export default meta;

type Story = StoryObj<typeof ScanActivity>;

export const RunningScheduled: Story = {
  args: { scan: runningScheduledScan },
};

export const Failed: Story = {
  args: { scan: failedScan },
};

export const MinimizeFlow: Story = {
  args: { scan: runningScheduledScan, open: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Minimize" }));
  },
};
