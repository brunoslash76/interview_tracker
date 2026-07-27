import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { Header } from "./Header";

const meta: Meta<typeof Header> = {
  title: "Header",
  component: Header,
  args: { connected: true, onScan: () => undefined },
};
export default meta;

type Story = StoryObj<typeof Header>;

export const Online: Story = {};

export const Offline: Story = {
  args: { connected: false },
};

export const SettingsNav: Story = {
  args: { settings: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Dashboard" })).toBeVisible();
  },
};

export const ThemeToggle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Light|Dark/ }));
  },
};
