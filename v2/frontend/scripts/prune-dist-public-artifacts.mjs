import { rm, stat, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distRoot = path.join(frontendRoot, 'dist');

const KEEP_TOP_LEVEL = new Set([
  'api',
  'assets',
  'brand',
  'favicon.svg',
  'icons',
  'index.html',
  'manifest.webmanifest',
  'service-worker.js',
]);

function shouldPruneTopLevel(entry) {
  if (KEEP_TOP_LEVEL.has(entry.name)) return false;
  return entry.isDirectory() || entry.isFile();
}

async function sizeBytes(target) {
  const info = await stat(target);
  if (!info.isDirectory()) return info.size;
  let total = 0;
  const entries = await readdir(target, { withFileTypes: true });
  for (const entry of entries) {
    total += await sizeBytes(path.join(target, entry.name));
  }
  return total;
}

async function main() {
  const entries = await readdir(distRoot, { withFileTypes: true });
  const pruned = [];
  for (const entry of entries) {
    if (!shouldPruneTopLevel(entry)) continue;
    const target = path.join(distRoot, entry.name);
    const bytes = await sizeBytes(target).catch(() => 0);
    await rm(target, { recursive: true, force: true });
    pruned.push({ name: entry.name, bytes });
  }
  const totalBytes = pruned.reduce((sum, row) => sum + row.bytes, 0);
  console.log(JSON.stringify({
    schema_version: 'frontend_dist_public_artifact_prune_v1',
    dist_root: path.relative(frontendRoot, distRoot),
    pruned_count: pruned.length,
    pruned_bytes: totalBytes,
    kept_top_level: [...KEEP_TOP_LEVEL].sort(),
    largest_pruned: pruned.sort((a, b) => b.bytes - a.bytes).slice(0, 10),
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
