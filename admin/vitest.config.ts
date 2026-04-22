import { defineConfig } from "vitest/config";
import path from "node:path";
import react from "@vitejs/plugin-react-swc";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    globals: false,
  },
});
