import { cp, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const curatedPublicEntries = [
  "api",
  "brand",
  "favicon.svg",
  "icons",
  "manifest.webmanifest",
  "service-worker.js",
];

// In Vite 8 + @vitejs/plugin-react 6, the React Refresh preamble (which
// defines window.$RefreshReg$ and window.$RefreshSig$) is injected via
// Rolldown's reactRefreshWrapperPlugin. When Rolldown is not installed, the
// preamble is never injected but every transformed React file still calls
// $RefreshSig$ at module evaluation time — crashing the app before React can
// mount. This plugin fills the gap: it injects the preamble manually on the
// dev server only, matching what @vitejs/plugin-react 4 used to do via
// transformIndexHtml.
const reactRefreshPreamble: Plugin = {
  name: "react-refresh-preamble",
  apply: "serve",
  transformIndexHtml() {
    return [
      {
        tag: "script",
        attrs: { type: "module" },
        injectTo: "head-prepend",
        children: [
          `import RefreshRuntime from "/@react-refresh";`,
          `RefreshRuntime.injectIntoGlobalHook(window);`,
          `window.$RefreshReg$ = () => {};`,
          `window.$RefreshSig$ = () => (type) => type;`,
          `window.__vite_plugin_react_preamble_installed__ = true;`,
        ].join("\n"),
      },
    ];
  },
};

const copyCuratedPublicAssets: Plugin = {
  name: "copy-curated-public-assets",
  apply: "build",
  async closeBundle() {
    const publicRoot = path.join(frontendRoot, "public");
    const distRoot = path.join(frontendRoot, "dist");
    await mkdir(distRoot, { recursive: true });
    await Promise.all(
      curatedPublicEntries.map(async (entry) => {
        await cp(path.join(publicRoot, entry), path.join(distRoot, entry), {
          errorOnExist: false,
          force: true,
          recursive: true,
        }).catch((error: NodeJS.ErrnoException) => {
          if (error.code !== "ENOENT") throw error;
        });
      }),
    );
  },
};

export default defineConfig(({ command }) => ({
  plugins: [reactRefreshPreamble, react(), copyCuratedPublicAssets],
  publicDir: command === "build" ? false : "public",
  server: {
    port: 5173,
    strictPort: true,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      "/ws": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      // Frontend-truth evidence payloads (public Simple Status page) are served
      // by the backend; without this proxy the SPA fallback returns index.html
      // and /status-simple never leaves its "connecting" state.
      "/operator_runtime": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
      },
    },
    allowedHosts: [
      "localhost",
      "127.0.0.1",
      "dashboard.wajidali.us",
    ],
  },
  preview: {
    port: 5173,
    strictPort: true,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      "/ws": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      // Same as server.proxy: frontend-truth payloads live on the backend.
      "/operator_runtime": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
}));
