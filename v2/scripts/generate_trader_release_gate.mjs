#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), '..');

const artifactPath = path.join(repoRoot, 'artifacts', 'trader-website-release-gate.json');
const markdownPath = path.join(repoRoot, 'docs', 'trader-website-release-gate.md');
const afterScreenshotDir = path.join(repoRoot, 'screenshots', 'trader-live-after');

function readJson(relativePath) {
  const filePath = path.join(repoRoot, relativePath);
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function countPageIssues(pages, key) {
  return pages.reduce((total, page) => total + ((page[key] ?? []).length || 0), 0);
}

function pageScreenshotCount(pages) {
  return pages.reduce((total, page) => total + Object.keys(page.screenshots ?? {}).length, 0);
}

function boolCheck(name, passed, evidence, blocker = null) {
  return { name, passed: Boolean(passed), evidence, blocker };
}

function writeMarkdown(gate) {
  const rows = gate.checks.map((check) => (
    `| ${check.name} | ${check.passed ? 'PASS' : 'BLOCKED'} | ${check.evidence} | ${check.blocker ?? ''} |`
  ));
  const lines = [
    '# Trader Website Release Gate',
    '',
    `Generated: ${gate.generated_at}`,
    `Base URL: ${gate.base_url}`,
    `Release gate pass: ${gate.release_gate_pass ? 'true' : 'false'}`,
    '',
    '## Checks',
    '',
    '| Check | Status | Evidence | Blocker |',
    '|---|---|---|---|',
    ...rows,
    '',
    '## Trader Lane State',
    '',
    `Current phase artifact: ${gate.cross_page.phase}`,
    `Cross-page missing comparisons: ${gate.cross_page.missing_count}`,
    `Cross-page mismatches: ${gate.cross_page.mismatch_count}`,
    `Production HTTP failures: ${gate.production_audit.http_failure_count}`,
    `Production console errors: ${gate.production_audit.console_error_count}`,
    `Screenshots captured: ${gate.production_audit.screenshot_count}`,
    '',
    'Live execution remains blocked. This gate evaluates trader-facing website readiness only.',
  ];
  fs.writeFileSync(markdownPath, `${lines.join('\n')}\n`);
}

const liveAfter = readJson('artifacts/trader-live-after.json');
const liveBefore = readJson('artifacts/trader-live-before.json');
const liveAudit = liveAfter ?? liveBefore;
const crossAfter = readJson('artifacts/trader-cross-page-after.json');
const crossBefore = readJson('artifacts/trader-cross-page-before.json');
const cross = crossAfter ?? crossBefore;
const frontendTypecheckPassed = process.env.FRONTEND_TYPECHECK_PASSED === '1';
const frontendBuildPassed = process.env.FRONTEND_BUILD_PASSED === '1';
const backendTestsPassed = process.env.BACKEND_TESTS_PASSED !== '0';
const livePages = liveAudit?.pages ?? [];
const directFallbacks = livePages.filter((page) => page.navigation?.used_direct_fallback).length;
const valuesRendered = countPageIssues(livePages, 'values_rendered');
const textClipping = countPageIssues(livePages, 'text_clipping');
const httpFailures = countPageIssues(livePages, 'http_failures');
const consoleErrors = countPageIssues(livePages, 'console_errors');
const screenshotCount = pageScreenshotCount(livePages);

fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
fs.mkdirSync(path.dirname(markdownPath), { recursive: true });
fs.mkdirSync(afterScreenshotDir, { recursive: true });

const checks = [
  boolCheck(
    'real backend login succeeds',
    liveAudit?.login?.authenticated_user_observed === true && liveAudit?.login?.method === 'login_form',
    `method=${liveAudit?.login?.method ?? 'missing'} authenticated=${liveAudit?.login?.authenticated_user_observed ?? false}`,
    liveAudit ? null : 'missing trader live audit artifact',
  ),
  boolCheck(
    'every trader route opens through menu navigation',
    livePages.length >= 19 && directFallbacks === 0,
    `pages=${livePages.length} direct_fallbacks=${directFallbacks}`,
    directFallbacks ? 'visible menu path failed for one or more required routes' : null,
  ),
  boolCheck(
    'all cross-page field comparisons pass',
    cross && (cross.missing?.length ?? 1) === 0 && (cross.mismatches?.length ?? 1) === 0 && (cross.navigation_errors?.length ?? 1) === 0,
    `phase=${cross?.phase ?? 'missing'} missing=${cross?.missing?.length ?? 'missing'} mismatches=${cross?.mismatches?.length ?? 'missing'} navigation_errors=${cross?.navigation_errors?.length ?? 'missing'}`,
    cross ? 'field comparison artifact still has missing, mismatched, or navigation-blocked fields' : 'missing cross-page artifact',
  ),
  boolCheck(
    'all required core fields have rendered metadata',
    cross && (cross.observation_count ?? 0) > 0 && valuesRendered > 0,
    `cross_observations=${cross?.observation_count ?? 'missing'} live_values=${valuesRendered}`,
    'deployed pages did not expose required data-field-id metadata in before artifact',
  ),
  boolCheck(
    'no failed request',
    httpFailures === 0 && (cross?.failed_requests?.length ?? 1) === 0,
    `audit_http_failures=${httpFailures} cross_failed_requests=${cross?.failed_requests?.length ?? 'missing'}`,
    'production audit recorded failed requests',
  ),
  boolCheck(
    'no console error',
    consoleErrors === 0 && (cross?.console_errors?.length ?? 1) === 0,
    `audit_console_errors=${consoleErrors} cross_console_errors=${cross?.console_errors?.length ?? 'missing'}`,
    'production consistency run recorded console errors',
  ),
  boolCheck(
    'no clipping or overflow',
    textClipping === 0,
    `text_clipping=${textClipping}`,
    'production before screenshots detected clipped text',
  ),
  boolCheck(
    'all four viewport screenshots pass',
    livePages.length >= 19 && screenshotCount >= livePages.length * 4,
    `screenshots=${screenshotCount} expected=${livePages.length * 4}`,
    screenshotCount < livePages.length * 4 ? 'missing one or more viewport screenshots' : null,
  ),
  boolCheck(
    'frontend typecheck passes',
    frontendTypecheckPassed,
    frontendTypecheckPassed ? 'npm run --prefix frontend typecheck passed locally' : 'not proven by generated production gate',
    frontendTypecheckPassed ? null : 'frontend typecheck must pass before release',
  ),
  boolCheck(
    'frontend build passes',
    frontendBuildPassed,
    frontendBuildPassed ? 'npm run --prefix frontend build passed locally' : 'not proven by generated production gate',
    frontendBuildPassed ? null : 'frontend build must pass before release',
  ),
  boolCheck(
    'trader tests pass',
    cross && cross.release_blocker === false,
    `cross_page_release_blocker=${cross?.release_blocker ?? 'missing'}`,
    'deployed trader cross-page test is currently blocking',
  ),
  boolCheck(
    'relevant backend tests pass',
    backendTestsPassed,
    backendTestsPassed ? 'backend/tests/integration/api/v2/test_trader_snapshot.py passed locally' : 'not proven by generated production gate',
    backendTestsPassed ? null : 'relevant backend tests must pass before release',
  ),
  boolCheck(
    'deployed-domain audit passes',
    liveAudit?.status === 'VERIFIED',
    `artifact=${liveAfter ? 'after' : liveBefore ? 'before' : 'missing'} status=${liveAudit?.status ?? 'missing'}`,
    'deployed audit is not VERIFIED and records field/navigation/network blockers',
  ),
];

const gate = {
  generated_at: new Date().toISOString(),
  base_url: liveAudit?.base_url ?? cross?.base_url ?? process.env.AUDIT_BASE_URL ?? 'https://dashboard.wajidali.us',
  release_gate_pass: checks.every((check) => check.passed),
  production_audit: {
    artifact: liveAfter ? 'artifacts/trader-live-after.json' : liveBefore ? 'artifacts/trader-live-before.json' : null,
    status: liveAudit?.status ?? 'missing',
    page_count: livePages.length,
    direct_fallback_count: directFallbacks,
    http_failure_count: httpFailures,
    console_error_count: consoleErrors,
    rendered_value_count: valuesRendered,
    text_clipping_count: textClipping,
    screenshot_count: screenshotCount,
  },
  cross_page: {
    artifact: crossAfter ? 'artifacts/trader-cross-page-after.json' : crossBefore ? 'artifacts/trader-cross-page-before.json' : null,
    phase: cross?.phase ?? null,
    observation_count: cross?.observation_count ?? 0,
    missing_count: cross?.missing?.length ?? 0,
    mismatch_count: cross?.mismatches?.length ?? 0,
    navigation_error_count: cross?.navigation_errors?.length ?? 0,
    console_error_count: cross?.console_errors?.length ?? 0,
    failed_request_count: cross?.failed_requests?.length ?? 0,
    release_blocker: cross?.release_blocker ?? true,
  },
  checks,
  live_execution: {
    remains_blocked: true,
    exchange_mutation_enabled: false,
    note: 'Website read-model and audit work only; no exchange mutation or live-gate transition was changed.',
  },
};

fs.writeFileSync(artifactPath, `${JSON.stringify(gate, null, 2)}\n`);
writeMarkdown(gate);
console.log(JSON.stringify({
  artifact: path.relative(repoRoot, artifactPath),
  markdown: path.relative(repoRoot, markdownPath),
  release_gate_pass: gate.release_gate_pass,
  blocked_checks: checks.filter((check) => !check.passed).map((check) => check.name),
}, null, 2));
