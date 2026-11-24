/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const engine = process.env.YESRULE_ENGINE ?? "http://localhost:8787";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/v1": engine, "/health": engine } },
  build: {
    outDir: "../engine/src/yesrule/web/dist",
    emptyOutDir: true,
    rolldownOptions: { output: { codeSplitting: { groups: [
      { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
      { name: "tanstack", test: /node_modules[\\/]@tanstack[\\/]/ },
      { name: "motion", test: /node_modules[\\/](motion|framer-motion|motion-dom|motion-utils)[\\/]/ },
      { name: "vendor", test: /node_modules/ },
    ] } } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
