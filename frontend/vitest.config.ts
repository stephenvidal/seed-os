/// <reference types="vitest/config" />
/**
 * Test-only config, deliberately separate from `vite.config.ts`.
 *
 * `vite.config.ts` loads the Tailwind v4 plugin. On the CI host (golden-eye: 4
 * vCPU Pentium 5405U, rotational disk, dozens of containers) that plugin spends
 * long enough in worker startup that vitest's forks pool gives up before the
 * worker answers:
 *   Error [vitest-pool]: Failed to start forks worker ... Timeout waiting for worker to respond
 * Tests never compile Tailwind, so this config keeps `react()` only and runs in a
 * single thread instead of one fork per file — measured on golden-eye: 12 passed
 * in 67s here, versus three worker-start errors with the Tailwind plugin loaded.
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
    poolOptions: { threads: { singleThread: true } },
  },
});
