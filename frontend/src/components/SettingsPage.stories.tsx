import type { Meta, StoryObj } from "@storybook/react";
import { userEvent, within } from "@storybook/test";
import { SettingsPage } from "./SettingsPage";

const meta: Meta<typeof SettingsPage> = {
  title: "SettingsPage",
  component: SettingsPage,
  args: {
    connected: true,
    settings: { email: "", scan_times: ["09:00"], max_scan_times: 5 },
    save: async (value) => ({ ...value, max_scan_times: 5 }),
  },
};
export default meta;

type Story = StoryObj<typeof SettingsPage>;

export const Default: Story = {};

export const SaveInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByLabelText("Email filter"), "story@example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Save and apply schedule" }));
  },
};
