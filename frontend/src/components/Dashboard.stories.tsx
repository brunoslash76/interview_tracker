import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { Dashboard } from "./Dashboard";
import { sampleInterviews } from "../fixtures/interviews";

const meta: Meta<typeof Dashboard> = {
  title: "Dashboard",
  component: Dashboard,
  args: {
    records: sampleInterviews,
    generatedAt: "just now",
    connected: true,
    onScan: () => undefined,
  },
};
export default meta;

type Story = StoryObj<typeof Dashboard>;

export const Default: Story = {};

export const Empty: Story = {
  args: { records: [] },
};

export const HighVolume: Story = {
  args: {
    records: Array.from({ length: 40 }, (_, index) => ({
      ...sampleInterviews[0],
      thread_id: `hv-${index}`,
      company: `Bulk ${index}`,
    })),
  },
};

export const FilterInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Search"), "Acme");
    await expect(canvas.getByText("Acme")).toBeVisible();
  },
};
