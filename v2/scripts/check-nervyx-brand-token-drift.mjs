#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '../..');
const sourceCandidates = [
  process.env.NERVYX_BRAND_TOKENS,
  resolve(repoRoot, 'rebranding/nervyx-one-brand-tokens.json'),
  resolve(repoRoot, '../rebranding/nervyx-one-brand-tokens.json'),
  resolve(process.cwd(), 'rebranding/nervyx-one-brand-tokens.json'),
  resolve(process.cwd(), '../rebranding/nervyx-one-brand-tokens.json'),
].filter(Boolean);
const sourcePath = sourceCandidates.find((candidate) => existsSync(candidate));
if (!sourcePath) throw new Error('Missing NERVYX source token file');

const sourceChecksum = createHash('sha256')
  .update(readFileSync(sourcePath, 'utf8'))
  .digest('hex');

const manifestPath = resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-theme-manifest.json');
const swiftTokensPath = resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift');
const swiftManifestPath = resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift');

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const swiftTokens = readFileSync(swiftTokensPath, 'utf8');
const swiftManifest = readFileSync(swiftManifestPath, 'utf8');

const failures = [];
if (manifest.sourceChecksum !== sourceChecksum) failures.push('web manifest checksum mismatch');
if (!swiftTokens.includes(sourceChecksum)) failures.push('Swift token checksum mismatch');
if (!swiftManifest.includes(sourceChecksum)) failures.push('Swift theme manifest checksum mismatch');
if (manifest.productName !== 'NERVYX ONE') failures.push('web manifest product mismatch');
if (!swiftManifest.includes('NERVYX ONE')) failures.push('Swift manifest product mismatch');

if (failures.length) {
  throw new Error(`NERVYX token drift detected: ${failures.join(', ')}`);
}

console.log(`NERVYX token drift check passed for checksum ${sourceChecksum}`);
