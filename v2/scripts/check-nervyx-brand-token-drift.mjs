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

const sourceRaw = readFileSync(sourcePath, 'utf8');
const source = JSON.parse(sourceRaw);
const sourceChecksum = createHash('sha256')
  .update(sourceRaw)
  .digest('hex');

const manifestPath = resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-theme-manifest.json');
const webTokensPath = resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-tokens.ts');
const webCssPath = resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-tokens.css');
const swiftTokensPath = resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift');
const swiftManifestPath = resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift');
const swiftBrandPath = resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/NervyxBrand.swift');

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const webTokensSource = readFileSync(webTokensPath, 'utf8');
const webCss = readFileSync(webCssPath, 'utf8');
const swiftTokens = readFileSync(swiftTokensPath, 'utf8');
const swiftManifest = readFileSync(swiftManifestPath, 'utf8');
const swiftBrand = readFileSync(swiftBrandPath, 'utf8');

const failures = [];

function fail(message) {
  failures.push(message);
}

function requireEqual(actual, expected, label) {
  if (actual !== expected) fail(`${label}: expected ${expected}, got ${actual}`);
}

function requireIncludes(body, needle, label) {
  if (!body.includes(needle)) fail(`${label}: missing ${needle}`);
}

function requireArrayEqual(actual, expected, label) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) fail(`${label}: expected ${e}, got ${a}`);
}

function parseWebTokens(text) {
  const prefix = 'export const nervyxTokens = ';
  const suffix = ' as const;';
  const start = text.indexOf(prefix);
  const end = text.lastIndexOf(suffix);
  if (start < 0 || end < 0 || end <= start) {
    fail('web tokens parse: generated TypeScript export shape changed');
    return null;
  }
  return JSON.parse(text.slice(start + prefix.length, end).trim());
}

function kebab(value) {
  return value.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
}

function publicSafeBrandText(value) {
  return String(value)
    .replace(/Paper\/live/g, 'Execution')
    .replace(/paper\/live/g, 'execution');
}

function swiftLetValues(body) {
  const values = new Map();
  const pattern = /public static let (`?)([A-Za-z][A-Za-z0-9_]*|guard)\1 = "([^"]+)"/g;
  for (const match of body.matchAll(pattern)) {
    values.set(match[2], match[3]);
  }
  return values;
}

function swiftString(value) {
  return `"${String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

const webTokens = parseWebTokens(webTokensSource);
const swiftTokenValues = swiftLetValues(swiftTokens);
const swiftManifestValues = swiftLetValues(swiftManifest);

if (webTokens) {
  requireEqual(manifest.sourceChecksum, sourceChecksum, 'web manifest checksum');
  requireEqual(webTokens.manifest.sourceChecksum, sourceChecksum, 'web tokens manifest checksum');
  requireEqual(swiftTokenValues.get('sourceChecksum'), sourceChecksum, 'Swift token checksum');
  requireEqual(swiftManifestValues.get('sourceChecksum'), sourceChecksum, 'Swift manifest checksum');

  requireEqual(manifest.productName, source.brand.name, 'web manifest product');
  requireEqual(manifest.descriptor, source.brand.descriptor, 'web manifest descriptor');
  requireEqual(manifest.tagline, source.brand.tagline, 'web manifest tagline');
  requireEqual(webTokens.brand.name, source.brand.name, 'web token brand name');
  requireEqual(webTokens.brand.descriptor, source.brand.descriptor, 'web token descriptor');
  requireEqual(webTokens.brand.tagline, source.brand.tagline, 'web token tagline');
  requireEqual(swiftManifestValues.get('productName'), source.brand.name, 'Swift manifest product');
  requireEqual(swiftManifestValues.get('descriptor'), source.brand.descriptor, 'Swift manifest descriptor');
  requireEqual(swiftManifestValues.get('tagline'), source.brand.tagline, 'Swift manifest tagline');

  for (const [themeId, theme] of Object.entries(source.themes)) {
    const generatedTheme = manifest.themes[themeId];
    if (!generatedTheme) {
      fail(`web manifest missing theme ${themeId}`);
      continue;
    }
    for (const [field, value] of Object.entries(theme)) {
      requireEqual(generatedTheme[field], value, `web manifest theme ${themeId}.${field}`);
      requireIncludes(swiftManifest, `${swiftString(field)}: ${swiftString(value)}`, `Swift manifest theme ${themeId}.${field}`);
    }
    requireIncludes(swiftManifest, `${swiftString(themeId)}: [`, `Swift manifest theme ${themeId}`);
    requireIncludes(swiftBrand, `case .${themeId}`, `Swift theme enum ${themeId}`);
  }

  requireArrayEqual(manifest.themes.midnightNeural.defaultFor, ['public', 'trader'], 'Midnight Neural access');
  requireArrayEqual(manifest.themes.polarSignal.selectableFor, ['public', 'trader'], 'Polar Signal access');
  requireArrayEqual(manifest.themes.opsTerminal.restrictedTo, ['admin', 'superadmin'], 'Ops Terminal access');
  requireIncludes(swiftManifest, '"midnightNeural": ["public", "trader"]', 'Swift Midnight Neural access');
  requireIncludes(swiftManifest, '"polarSignal": ["public", "trader"]', 'Swift Polar Signal access');
  requireIncludes(swiftManifest, '"opsTerminal": ["admin", "superadmin"]', 'Swift Ops Terminal access');
  requireIncludes(swiftBrand, 'theme == .opsTerminal && !backendConfirmedAdmin', 'Swift Ops Terminal backend role restriction');

  const expectedModules = {
    sense: { displayName: 'NERVYX SENSE', description: publicSafeBrandText(source.modules['NERVYX SENSE']) },
    core: { displayName: 'NERVYX CORE', description: publicSafeBrandText(source.modules['NERVYX CORE']) },
    shift: { displayName: 'NERVYX SHIFT', description: publicSafeBrandText(source.modules['NERVYX SHIFT']) },
    guard: { displayName: 'NERVYX GUARD', description: publicSafeBrandText(source.modules['NERVYX GUARD']) },
    replay: { displayName: 'NERVYX REPLAY', description: publicSafeBrandText(source.modules['NERVYX REPLAY']) },
    execute: { displayName: 'NERVYX EXECUTE', description: publicSafeBrandText(source.modules['NERVYX EXECUTE']) },
    observe: { displayName: 'NERVYX OBSERVE', description: publicSafeBrandText(source.modules['NERVYX OBSERVE']) },
  };
  for (const [moduleId, module] of Object.entries(expectedModules)) {
    requireEqual(manifest.modules[moduleId]?.displayName, module.displayName, `web manifest module ${moduleId}.displayName`);
    requireEqual(manifest.modules[moduleId]?.description, module.description, `web manifest module ${moduleId}.description`);
    requireIncludes(swiftManifest, `${swiftString(moduleId)}: [`, `Swift manifest module ${moduleId}`);
    requireIncludes(swiftManifest, `${swiftString('displayName')}: ${swiftString(module.displayName)}`, `Swift manifest module ${moduleId}.displayName`);
    requireIncludes(swiftManifest, `${swiftString('description')}: ${swiftString(module.description)}`, `Swift manifest module ${moduleId}.description`);
  }

  for (const [name, value] of Object.entries(webTokens.semanticColors)) {
    requireEqual(swiftTokenValues.get(name), value, `Swift semantic color ${name}`);
    requireIncludes(webCss, `--nervyx-${kebab(name)}: ${value};`, `CSS semantic color ${name}`);
  }

  for (const [scaleName, scale] of Object.entries(webTokens.scales)) {
    requireIncludes(swiftTokens, `public static let ${scaleName}: [String: String]`, `Swift scale ${scaleName}`);
    for (const [key, value] of Object.entries(scale)) {
      requireIncludes(swiftTokens, `${swiftString(key)}: ${swiftString(value)}`, `Swift scale ${scaleName}.${key}`);
    }
  }

  requireIncludes(webCss, ':root, [data-nervyx-theme="midnight-neural"]', 'CSS Midnight Neural selector');
  requireIncludes(webCss, '[data-nervyx-theme="polar-signal"]', 'CSS Polar Signal selector');
  requireIncludes(webCss, '[data-nervyx-theme="ops-terminal"]', 'CSS Ops Terminal selector');
  requireIncludes(webCss, `--nervyx-background-base: ${source.themes.polarSignal.background};`, 'CSS Polar Signal background');
  requireIncludes(webCss, `--nervyx-background-base: ${source.themes.opsTerminal.background};`, 'CSS Ops Terminal background');
}

if (failures.length) {
  throw new Error(`NERVYX token drift detected:\n- ${failures.join('\n- ')}`);
}

console.log(`NERVYX token drift check passed for checksum ${sourceChecksum}`);
