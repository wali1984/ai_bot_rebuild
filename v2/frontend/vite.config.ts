import { createReadStream } from "node:fs";
import { cp, mkdir, stat } from "node:fs/promises";
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
  // Report-center static payloads consumed by /admin/reports
  // (REPORTS_ENDPOINT = /v2_report_center/latest/report_index.json). Without
  // this entry the SPA fallback serves index.html for that path and the whole
  // reports view dies with a false "report center not generating" incident.
  "v2_report_center",
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

// The deployed site runs `vite preview` against dist/, but dist/ deliberately
// prunes the operator evidence payload directories (public/ is ~12 GB and the
// payload generators rewrite files continuously — a build-time copy would both
// bloat dist and go stale). Without this middleware every payload-file fetch
// (/v2_report_center/*, /system_atlas_runtime_coverage/*,
// /external_manual_position_quarantine/*, /enterprise_trading_cockpit/*,
// /autonomous_governor/*, operator-truth payloads, …) fell through to the SPA
// fallback, returned index.html, and killed the page with a JSON parse error.
// Serve those files straight from public/ at request time so they stay fresh.
// /api, /ws and /operator_runtime are excluded — they are proxied to the
// backend (:8000), which owns fresher copies of operator_runtime payloads.
const servePublicEvidencePayloads: Plugin = {
  name: "serve-public-evidence-payloads",
  configurePreviewServer(server) {
    const publicRoot = path.join(frontendRoot, "public");
    server.middlewares.use((req, res, next) => {
      void (async () => {
        try {
          if (req.method !== "GET" && req.method !== "HEAD") return next();
          const rawPath = (req.url ?? "").split("?")[0];
          if (!rawPath.startsWith("/")) return next();
          if (
            rawPath.startsWith("/api/") ||
            rawPath.startsWith("/ws") ||
            rawPath.startsWith("/operator_runtime/") ||
            rawPath.startsWith("/assets/")
          ) {
            return next();
          }
          let decoded: string;
          try {
            decoded = decodeURIComponent(rawPath);
          } catch {
            return next();
          }
          const resolved = path.resolve(publicRoot, `.${decoded}`);
          if (resolved !== publicRoot && !resolved.startsWith(publicRoot + path.sep)) return next();
          const fileStat = await stat(resolved).catch(() => null);
          if (!fileStat || !fileStat.isFile()) return next();
          const ext = path.extname(resolved).toLowerCase();
          const contentType =
            ext === ".json" ? "application/json; charset=utf-8"
            : ext === ".md" ? "text/markdown; charset=utf-8"
            : ext === ".txt" || ext === ".log" ? "text/plain; charset=utf-8"
            : ext === ".html" ? "text/html; charset=utf-8"
            : ext === ".svg" ? "image/svg+xml"
            : ext === ".png" ? "image/png"
            // service-worker.js / manifest live in public/ and are intercepted
            // here; a non-JS MIME type makes the browser refuse SW registration.
            : ext === ".js" || ext === ".mjs" ? "text/javascript; charset=utf-8"
            : ext === ".css" ? "text/css; charset=utf-8"
            : ext === ".webmanifest" ? "application/manifest+json; charset=utf-8"
            : "application/octet-stream";
          res.statusCode = 200;
          res.setHeader("Content-Type", contentType);
          res.setHeader("Content-Length", String(fileStat.size));
          // Evidence payloads are rewritten in place by their generators —
          // never let the browser cache a stale copy.
          res.setHeader("Cache-Control", "no-store");
          if (req.method === "HEAD") return res.end();
          createReadStream(resolved).pipe(res);
        } catch {
          next();
        }
      })();
    });
  },
};

export default defineConfig(({ command }) => ({
  plugins: [reactRefreshPreamble, react(), copyCuratedPublicAssets, servePublicEvidencePayloads],
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
