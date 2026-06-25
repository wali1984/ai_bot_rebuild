import { expect, test } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const e2eDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(e2eDir, '../../../..');
const tokenSourcePath = path.join(workspaceRoot, 'rebranding/nervyx-one-brand-tokens.json');
const webManifestPath = path.resolve(e2eDir, '../../src/brand/generated/nervyx-theme-manifest.json');
const webTokensPath = path.resolve(e2eDir, '../../src/brand/generated/nervyx-tokens.ts');
const swiftManifestPath = path.resolve(e2eDir, '../../../mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift');
const swiftTokensPath = path.resolve(e2eDir, '../../../mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift');
const swiftBrandPath = path.resolve(e2eDir, '../../../mobile/Sources/AIBotV2/Brand/NervyxBrand.swift');

function sha256(filePath: string): string {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

test('NERVYX web and Swift generated themes derive from the /rebranding token source', () => {
  const sourceChecksum = sha256(tokenSourcePath);
  const sourceTokens = JSON.parse(fs.readFileSync(tokenSourcePath, 'utf8')) as {
    brand: { name: string; descriptor: string; tagline: string };
    themes: Record<string, Record<string, string>>;
  };
  const webManifest = JSON.parse(fs.readFileSync(webManifestPath, 'utf8')) as {
    productName: string;
    descriptor: string;
    tagline: string;
    sourceChecksum: string;
    themes: Record<string, Record<string, string | string[]>>;
  };
  const webTokens = fs.readFileSync(webTokensPath, 'utf8');
  const swiftManifest = fs.readFileSync(swiftManifestPath, 'utf8');
  const swiftTokens = fs.readFileSync(swiftTokensPath, 'utf8');
  const swiftBrand = fs.readFileSync(swiftBrandPath, 'utf8');

  expect(webManifest.sourceChecksum).toBe(sourceChecksum);
  expect(webTokens).toContain(`"sourceChecksum": "${sourceChecksum}"`);
  expect(swiftManifest).toContain(`sourceChecksum = "${sourceChecksum}"`);
  expect(swiftTokens).toContain(`sourceChecksum = "${sourceChecksum}"`);

  expect(webManifest.productName).toBe(sourceTokens.brand.name);
  expect(webManifest.descriptor).toBe(sourceTokens.brand.descriptor);
  expect(webManifest.tagline).toBe(sourceTokens.brand.tagline);

  for (const [themeId, theme] of Object.entries(sourceTokens.themes)) {
    expect(webManifest.themes[themeId]).toMatchObject(theme);
    expect(swiftBrand).toContain(themeId);
    expect(swiftBrand).toContain(String(webManifest.themes[themeId].name));
  }

  expect(webManifest.themes.midnightNeural.defaultFor).toEqual(['public', 'trader']);
  expect(webManifest.themes.polarSignal.selectableFor).toEqual(['public', 'trader']);
  expect(webManifest.themes.opsTerminal.restrictedTo).toEqual(['admin', 'superadmin']);
  expect(swiftBrand).toContain('theme == .opsTerminal && !backendConfirmedAdmin');
});
