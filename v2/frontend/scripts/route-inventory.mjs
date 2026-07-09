import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, '..');
const pagesRoot = resolve(frontendRoot, 'src', 'pages');
const registryPath = resolve(pagesRoot, 'registry.ts');
const navigationPath = resolve(pagesRoot, 'productNavigation.ts');

function read(path) {
  return readFileSync(path, 'utf8');
}

function extractRegisteredPages() {
  const registry = read(registryPath);
  const imports = new Map();
  for (const match of registry.matchAll(/import\s+(\w+)(?:Meta|Route)?\s+from\s+'\.\/([^']+)\/(meta|route)'/g)) {
    imports.set(match[1], { dir: match[2], kind: match[3] });
  }

  const rawBlock = registry.match(/const RAW_PAGES:[\s\S]*?=\s*\[([\s\S]*?)\];\s*\n\nexport const PAGES/)?.[1] ?? '';
  const entries = [];
  for (const match of rawBlock.matchAll(/meta:\s*(\w+),[\s\S]*?route:\s*(\w+),[\s\S]*?Component:\s*(\w+)/g)) {
    const metaImport = imports.get(match[1]);
    const routeImport = imports.get(match[2]);
    if (!metaImport || !routeImport) continue;
    const metaPath = resolve(pagesRoot, metaImport.dir, 'meta.ts');
    const routePath = resolve(pagesRoot, routeImport.dir, 'route.ts');
    if (!existsSync(metaPath) || !existsSync(routePath)) continue;
    const meta = read(metaPath);
    const route = read(routePath);
    const id = meta.match(/id:\s*['"]([^'"]+)['"]/)?.[1] ?? metaImport.dir;
    const rawPath = route.match(/path:\s*['"]([^'"]+)['"]/)?.[1] ?? null;
    if (rawPath) entries.push({ id, dir: routeImport.dir, rawPath });
  }
  return entries;
}

function extractOverrides() {
  const navigation = read(navigationPath);
  const overrides = new Map();
  for (const match of navigation.matchAll(/['"]([^'"]+)['"]:\s*\{([\s\S]*?)\n\s*\}/g)) {
    const path = match[2].match(/path:\s*['"]([^'"]+)['"]/)?.[1];
    if (path) overrides.set(match[1], path);
  }
  return overrides;
}

function extractLegacyRedirects() {
  const navigation = read(navigationPath);
  const block = navigation.match(/export const MERGED_LEGACY_PATHS:[\s\S]*?=\s*\{([\s\S]*?)\n\};/)?.[1] ?? '';
  const redirects = new Map();
  for (const match of block.matchAll(/['"]([^'"]+)['"]:\s*['"]([^'"]+)['"]/g)) {
    redirects.set(match[1], match[2]);
  }
  return redirects;
}

function materializeRoute(path) {
  return path
    .replace('/:symbol?', '/BTCUSDT')
    .replace('/:name?', '')
    .replace(/:symbol\?/g, 'BTCUSDT')
    .replace(/:name\?/g, '')
    .replace(/\/+$/g, '') || '/';
}

function withRoleQuery(path) {
  if (!path.startsWith('/admin')) return path;
  return path.includes('?') ? path : `${path}?role=admin`;
}

export function buildRouteInventory() {
  const overrides = extractOverrides();
  const legacyRedirects = extractLegacyRedirects();
  const entries = extractRegisteredPages().map((entry) => {
    const resolvedPath = overrides.get(entry.id) ?? entry.rawPath;
    return {
      ...entry,
      resolvedPath,
      redirectedTo: legacyRedirects.get(resolvedPath) ?? null,
      crawlPath: withRoleQuery(materializeRoute(resolvedPath)),
    };
  });
  return { entries, legacyRedirects };
}

export function buildWebsiteCrawlRoutes() {
  const { entries, legacyRedirects } = buildRouteInventory();
  const seen = new Set();
  const routes = ['/'];
  for (const entry of entries) {
    if (entry.redirectedTo || legacyRedirects.has(entry.resolvedPath)) continue;
    if (seen.has(entry.crawlPath)) continue;
    seen.add(entry.crawlPath);
    routes.push(entry.crawlPath);
  }
  return routes;
}

export function buildLegacyRedirectRoutes() {
  const { legacyRedirects } = buildRouteInventory();
  return [...legacyRedirects.entries()].map(([from, to]) => ({ from, to }));
}
