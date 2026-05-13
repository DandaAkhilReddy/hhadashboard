import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "node",
    globals: false,
    include: ["__tests__/**/*.test.ts", "__tests__/**/*.test.tsx"],
    // Coverage configuration — Phase 3 of the plan (96 line / 85 branch).
    // Stair-stepped via CI; thresholds here stay at 0 so local
    // `npm run test` stays fast and unblocked.
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "json-summary", "lcov"],
      include: ["app/**", "components/**", "lib/**", "middleware.ts"],
      exclude: [
        "**/*.d.ts",
        "**/api-types.ts", // generated from openapi-typescript
        "**/node_modules/**",
        "__tests__/**",
        "e2e/**",
        "**/*.config.{ts,js,mjs}",
      ],
      thresholds: {
        lines: 0,
        branches: 0,
        functions: 0,
        statements: 0,
      },
      reportsDirectory: "./coverage",
    },
  },
});
