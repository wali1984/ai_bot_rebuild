import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

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

export default defineConfig({
  plugins: [reactRefreshPreamble, react()],
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
      },
      "/ws": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
