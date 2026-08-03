#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
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
if (!sourcePath) {
  throw new Error(`Missing NERVYX brand token source. Tried: ${sourceCandidates.join(', ')}`);
}

const raw = readFileSync(sourcePath, 'utf8');
const source = JSON.parse(raw);
const checksum = createHash('sha256').update(raw).digest('hex');

const c = source.colors;
const themes = source.themes;
const modules = source.modules;

const semanticColors = {
  brandPrimary: c.primary,
  brandSecondary: c.primaryBlue,
  neuralAccent: c.primary,
  signalAccent: c.signal,
  inferenceAccent: c.primaryBlue,
  validationAccent: c.proof,
  executionAccent: c.info,
  backgroundBase: c.canvas,
  backgroundElevated: c.surface,
  panel: c.surface,
  panelElevated: c.surfaceElevated,
  overlay: '#05070DCC',
  hover: '#1E2840',
  selected: '#1C3442',
  borderSubtle: '#253044',
  borderStrong: '#3B4962',
  textPrimary: c.textPrimary,
  textSecondary: '#CBD5E1',
  textMuted: c.textMuted,
  textInverse: '#070A12',
  textLink: c.signal,
  buy: '#21C784',
  sell: c.danger,
  profit: c.proof,
  loss: c.danger,
  neutral: c.textMuted,
  positionLong: '#21C784',
  positionShort: c.danger,
  success: c.proof,
  warning: c.warning,
  error: c.danger,
  critical: '#FF2E55',
  unavailable: '#64748B',
  stale: c.warning,
  delayed: c.info,
  paper: '#8FD3FF',
  liveBlocked: c.danger,
  sense: c.signal,
  core: c.primary,
  shift: c.primaryBlue,
  guard: c.proof,
  replay: '#B794F4',
  execute: c.info,
  observe: '#A5B4FC',
  candleUp: '#21C784',
  candleDown: c.danger,
  volumeUp: '#1A9F6A',
  volumeDown: '#C64860',
  chartGrid: '#1F2937',
  crosshair: '#E2E8F0',
  predictionBand: '#4B7BFF44',
  target: c.proof,
  stop: c.danger,
  funding: c.signal,
  openInterest: c.primaryBlue,
  liquidationLong: '#FF9F1C',
  liquidationShort: '#FF5D7A',
};

const scales = {
  typography: {
    displayFamily: source.typography.display,
    interfaceFamily: source.typography.interface,
    dataFamily: source.typography.data,
    xs: '0.75rem',
    sm: '0.875rem',
    md: '1rem',
    lg: '1.125rem',
    xl: '1.5rem',
    xxl: '2rem',
  },
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '12px',
    lg: '16px',
    xl: '24px',
    xxl: '32px',
  },
  radius: {
    xs: '4px',
    sm: '6px',
    md: '8px',
    lg: '12px',
    xl: '16px',
  },
  shadow: {
    panel: '0 18px 60px rgba(0, 0, 0, 0.30)',
    focus: '0 0 0 3px rgba(34, 211, 197, 0.28)',
  },
  motion: {
    fast: '120ms',
    standard: '180ms',
    slow: '260ms',
  },
  elevation: {
    base: '0',
    header: '900',
    banner: '1000',
    modal: '1200',
  },
};

function publicSafeBrandText(value) {
  return String(value)
    .replace(/Paper\/live/g, 'Execution')
    .replace(/paper\/live/g, 'execution');
}

const manifest = {
  productName: source.brand.name,
  descriptor: source.brand.descriptor,
  tagline: source.brand.tagline,
  secondaryLine: 'One system. Every market state.',
  themes: {
    midnightNeural: {
      name: 'Midnight Neural',
      defaultFor: ['public', 'trader'],
      ...themes.midnightNeural,
    },
    polarSignal: {
      name: 'Polar Signal',
      selectableFor: ['public', 'trader'],
      ...themes.polarSignal,
    },
    opsTerminal: {
      name: 'Ops Terminal',
      restrictedTo: ['admin', 'superadmin'],
      ...themes.opsTerminal,
    },
  },
  modules: {
    sense: { displayName: 'NERVYX SENSE', description: publicSafeBrandText(modules['NERVYX SENSE']) },
    core: { displayName: 'NERVYX CORE', description: publicSafeBrandText(modules['NERVYX CORE']) },
    shift: { displayName: 'NERVYX SHIFT', description: publicSafeBrandText(modules['NERVYX SHIFT']) },
    guard: { displayName: 'NERVYX GUARD', description: publicSafeBrandText(modules['NERVYX GUARD']) },
    replay: { displayName: 'NERVYX REPLAY', description: publicSafeBrandText(modules['NERVYX REPLAY']) },
    execute: { displayName: 'NERVYX EXECUTE', description: publicSafeBrandText(modules['NERVYX EXECUTE']) },
    observe: { displayName: 'NERVYX OBSERVE', description: publicSafeBrandText(modules['NERVYX OBSERVE']) },
  },
  tokenVersion: checksum.slice(0, 12),
  assetVersion: checksum.slice(0, 12),
  sourceChecksum: checksum,
};

const generated = {
  brand: source.brand,
  semanticColors,
  scales,
  manifest,
};

function kebab(value) {
  return value.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
}

function cssVar(name) {
  return `--nervyx-${kebab(name)}`;
}

function write(path, body) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, body);
}

const cssLines = [
  '/* Generated by scripts/generate-nervyx-brand-tokens.mjs. Do not edit. */',
  ':root, [data-nervyx-theme="midnight-neural"] {',
];
for (const [name, value] of Object.entries(semanticColors)) {
  cssLines.push(`  ${cssVar(name)}: ${value};`);
}
for (const [name, value] of Object.entries(scales.typography)) cssLines.push(`  --nervyx-type-${kebab(name)}: ${value};`);
for (const [name, value] of Object.entries(scales.spacing)) cssLines.push(`  --nervyx-space-${kebab(name)}: ${value};`);
for (const [name, value] of Object.entries(scales.radius)) cssLines.push(`  --nervyx-radius-${kebab(name)}: ${value};`);
for (const [name, value] of Object.entries(scales.shadow)) cssLines.push(`  --nervyx-shadow-${kebab(name)}: ${value};`);
for (const [name, value] of Object.entries(scales.motion)) cssLines.push(`  --nervyx-motion-${kebab(name)}: ${value};`);
for (const [name, value] of Object.entries(scales.elevation)) cssLines.push(`  --nervyx-z-${kebab(name)}: ${value};`);
cssLines.push('}');
cssLines.push('[data-nervyx-theme="polar-signal"] {');
cssLines.push(`  --nervyx-background-base: ${themes.polarSignal.background};`);
cssLines.push(`  --nervyx-background-elevated: ${themes.polarSignal.surface};`);
cssLines.push(`  --nervyx-panel: ${themes.polarSignal.surface};`);
cssLines.push(`  --nervyx-panel-elevated: ${themes.polarSignal.surface2};`);
cssLines.push(`  --nervyx-text-primary: ${themes.polarSignal.text};`);
cssLines.push(`  --nervyx-text-secondary: #334155;`);
cssLines.push(`  --nervyx-text-muted: ${themes.polarSignal.muted};`);
cssLines.push(`  --nervyx-text-inverse: #F6F7FB;`);
cssLines.push(`  --nervyx-border-subtle: #D9E1EE;`);
cssLines.push(`  --nervyx-border-strong: #B8C3D6;`);
cssLines.push('}');
cssLines.push('[data-nervyx-theme="ops-terminal"] {');
cssLines.push(`  --nervyx-background-base: ${themes.opsTerminal.background};`);
cssLines.push(`  --nervyx-background-elevated: ${themes.opsTerminal.surface};`);
cssLines.push(`  --nervyx-panel: ${themes.opsTerminal.surface};`);
cssLines.push(`  --nervyx-panel-elevated: ${themes.opsTerminal.surface2};`);
cssLines.push(`  --nervyx-text-primary: ${themes.opsTerminal.text};`);
cssLines.push(`  --nervyx-text-secondary: #C5CDD5;`);
cssLines.push(`  --nervyx-text-muted: ${themes.opsTerminal.muted};`);
cssLines.push(`  --nervyx-signal-accent: ${themes.opsTerminal.accent};`);
cssLines.push('}');
cssLines.push('');

write(
  resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-tokens.css'),
  cssLines.join('\n'),
);
write(
  resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-tokens.ts'),
  `// Generated by scripts/generate-nervyx-brand-tokens.mjs. Do not edit.\nexport const nervyxTokens = ${JSON.stringify(generated, null, 2)} as const;\n`,
);
write(
  resolve(repoRoot, 'v2/frontend/src/brand/generated/nervyx-theme-manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
);

function swiftIdentifier(value) {
  return value === 'guard' ? '`guard`' : value;
}

const swiftColorLines = Object.entries(semanticColors)
  .map(([name, value]) => `    public static let ${swiftIdentifier(name)} = "${value}"`)
  .join('\n');
function swiftDictionary(values) {
  const entries = Object.entries(values)
    .map(([key, value]) => `${swiftString(key)}: ${swiftString(value)}`)
    .join(', ');
  return `[${entries}]`;
}

function swiftString(value) {
  return `"${String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function swiftNestedStringDictionary(values) {
  const entries = Object.entries(values)
    .map(([key, nested]) => `${swiftString(key)}: ${swiftDictionary(nested)}`)
    .join(', ');
  return `[${entries}]`;
}

function swiftStringArrayDictionary(values) {
  const entries = Object.entries(values)
    .map(([key, list]) => `${swiftString(key)}: [${list.map(swiftString).join(', ')}]`)
    .join(', ');
  return `[${entries}]`;
}

const swiftScaleLines = [
  `    public static let typography: [String: String] = ${swiftDictionary(scales.typography)}`,
  `    public static let spacing: [String: String] = ${swiftDictionary(scales.spacing)}`,
  `    public static let radius: [String: String] = ${swiftDictionary(scales.radius)}`,
  `    public static let shadow: [String: String] = ${swiftDictionary(scales.shadow)}`,
  `    public static let motion: [String: String] = ${swiftDictionary(scales.motion)}`,
  `    public static let elevation: [String: String] = ${swiftDictionary(scales.elevation)}`,
].join('\n');
const swiftThemes = Object.fromEntries(
  Object.entries(manifest.themes).map(([key, theme]) => [
    key,
    {
      name: theme.name,
      background: theme.background,
      surface: theme.surface,
      surface2: theme.surface2,
      text: theme.text,
      muted: theme.muted,
      accent: theme.accent,
    },
  ]),
);
const swiftThemeAccess = {
  midnightNeural: manifest.themes.midnightNeural.defaultFor,
  polarSignal: manifest.themes.polarSignal.selectableFor,
  opsTerminal: manifest.themes.opsTerminal.restrictedTo,
};
const swiftModules = Object.fromEntries(
  Object.entries(manifest.modules).map(([key, module]) => [
    key,
    {
      displayName: module.displayName,
      description: module.description,
    },
  ]),
);
write(
  resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift'),
  `// Generated by scripts/generate-nervyx-brand-tokens.mjs. Do not edit.\nimport Foundation\n\npublic enum NervyxGeneratedTokens {\n    public static let sourceChecksum = "${checksum}"\n${swiftColorLines}\n\n${swiftScaleLines}\n}\n`,
);
write(
  resolve(repoRoot, 'v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift'),
  `// Generated by scripts/generate-nervyx-brand-tokens.mjs. Do not edit.\nimport Foundation\n\npublic enum NervyxGeneratedThemeManifest {\n    public static let productName = "${manifest.productName}"\n    public static let descriptor = "${manifest.descriptor}"\n    public static let tagline = "${manifest.tagline}"\n    public static let secondaryLine = "${manifest.secondaryLine}"\n    public static let tokenVersion = "${manifest.tokenVersion}"\n    public static let assetVersion = "${manifest.assetVersion}"\n    public static let sourceChecksum = "${checksum}"\n    public static let themes: [String: [String: String]] = ${swiftNestedStringDictionary(swiftThemes)}\n    public static let themeAccess: [String: [String]] = ${swiftStringArrayDictionary(swiftThemeAccess)}\n    public static let modules: [String: [String: String]] = ${swiftNestedStringDictionary(swiftModules)}\n}\n`,
);

console.log(`Generated NERVYX tokens from source checksum ${checksum}`);
