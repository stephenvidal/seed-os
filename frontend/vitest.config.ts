/// <reference types="vitest/config" />
/**
 * Test-only config, deliberately separate from `vite.config.ts`.
 *
 * `vite.config.ts` loads the Tailwind v4 plugin, and tests have no use for it.
 * While CI ran on a small self-hosted box, that plugin cost enough worker startup
 * time to trip vitest's pool timeout and collect zero test files:
 *   Error [vitest-pool]: Failed to start forks worker ... Timeout waiting for worker to respond
 * CI is on hosted runners now, but the split is still worth keeping: the test run is
 * independent of CSS tooling and collects faster.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    pool: "threads",
    // Vitest 4+ dropped poolOptions; one worker replaces threads.singleThread.
    maxWorkers: 1,
  },
});
