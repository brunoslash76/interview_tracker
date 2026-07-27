import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  addons: ["@storybook/addon-essentials", "@storybook/addon-a11y"],
  framework: { name: "@storybook/react-vite", options: {} },
  docs: { autodocs: "tag" },
  async viteFinal(viteConfig) {
    return {
      ...viteConfig,
      build: {
        ...viteConfig.build,
        chunkSizeWarningLimit: 1000,
      },
    };
  },
};
export default config;
