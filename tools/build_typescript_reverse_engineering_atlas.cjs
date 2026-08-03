#!/usr/bin/env node
/*
 * TypeScript-compiler-AST companion for build_system_reverse_engineering_atlas.py.
 *
 * Static and secret-safe: tracked TS/TSX/JS/JSX/MJS/CJS files only; no module
 * imports from the application, no network, no runtime state.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const crypto = require('crypto');

const CODE_SUFFIX_RE = /\.(?:ts|tsx|js|jsx|mjs|cjs)$/i;
const SECRET_PATH_PARTS = new Set(['.local_secrets', 'secrets', '.ssh', '.aws']);
const SECRET_NAME_RE = /(?:^|[_.-])(secret|credential|private[_-]?key|auth[_-]?users?|auth[_-]?revocations?)(?:[_.-]|$)/i;
const SENSITIVE_LABEL = '(?:password|passwd|pwd|secret|credential|(?:api|access|refresh|auth|bearer|session)[_-]?token|token|api[_-]?key|apikey|access[_-]?key|account[_-]?key|private[_-]?key|signing[_-]?key|encryption[_-]?key|license[_-]?key|client[_-]?secret|webhook[_-]?url|connection[_-]?string|authorization|cookie|sig|dsn)';
const REDACTED = '[REDACTED]';
const compilerProvenance = new WeakMap();

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--repo-root' || token === '--out') {
      result[token.slice(2)] = argv[i + 1];
      i += 1;
    } else if (token === '--self-test') {
      result.selfTest = true;
    }
  }
  return result;
}

function isWithin(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function isSecretClassifiedPath(relPath) {
  const normalized = relPath.replace(/\\/g, '/');
  const parts = normalized.split('/').filter(Boolean);
  const lowerParts = new Set(parts.map((part) => part.toLowerCase()));
  const name = (parts[parts.length - 1] || '').toLowerCase();
  if ([...SECRET_PATH_PARTS].some((part) => lowerParts.has(part))) return true;
  if (name === '.env' || name.startsWith('.env.') || name.endsWith('.env')) return true;
  if (['auth_users.json', 'auth_revocations.json', 'trader_accounts.json'].includes(name)) return true;
  // Match the Python atlas policy: source files that merely implement secret
  // handling stay visible, while secret-like non-source artifacts are excluded.
  if (CODE_SUFFIX_RE.test(name)) return false;
  return SECRET_NAME_RE.test(name);
}

function trackedLockfiles(repoRoot) {
  const raw = childProcess.execFileSync('git', ['ls-files', '-z', '*package-lock.json'], { cwd: repoRoot });
  return raw
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .filter((relPath) => !isSecretClassifiedPath(relPath))
    .sort();
}

function lockedTypeScriptCandidates(repoRoot) {
  const repoReal = fs.realpathSync(repoRoot);
  const candidates = [];
  for (const lockRel of trackedLockfiles(repoRoot)) {
    const lockPath = path.resolve(repoRoot, lockRel);
    if (!isWithin(repoReal, lockPath)) continue;
    let lock;
    let lockfileSha256;
    try {
      const lockReal = fs.realpathSync(lockPath);
      if (lockReal !== lockPath || !isWithin(repoReal, lockReal) || !fs.statSync(lockReal).isFile()) continue;
      const lockBytes = fs.readFileSync(lockReal);
      lock = JSON.parse(lockBytes.toString('utf8'));
      lockfileSha256 = sha256(lockBytes);
    } catch (_) {
      continue;
    }
    const lockRoot = path.dirname(lockPath);
    const packageEntries = lock && lock.packages && typeof lock.packages === 'object'
      ? Object.entries(lock.packages).filter(([entryPath]) => /(?:^|\/)node_modules\/typescript$/.test(entryPath))
      : [];
    for (const [entryPath, entry] of packageEntries) {
      if (!entry || typeof entry.version !== 'string') continue;
      const packagePath = path.resolve(lockRoot, entryPath);
      if (!isWithin(lockRoot, packagePath) || !isWithin(repoReal, packagePath)) continue;
      candidates.push({
        lockRel,
        lockfileVersion: lock.lockfileVersion || null,
        lockfileSha256,
        packagePath,
        packageRel: path.relative(repoReal, packagePath).replace(/\\/g, '/'),
        version: entry.version,
        integrity: typeof entry.integrity === 'string' ? entry.integrity : null,
      });
    }
    if (packageEntries.length === 0 && lock.dependencies && lock.dependencies.typescript) {
      const entry = lock.dependencies.typescript;
      if (entry && typeof entry.version === 'string') {
        const packagePath = path.resolve(lockRoot, 'node_modules', 'typescript');
        if (isWithin(lockRoot, packagePath) && isWithin(repoReal, packagePath)) {
          candidates.push({
            lockRel,
            lockfileVersion: lock.lockfileVersion || null,
            lockfileSha256,
            packagePath,
            packageRel: path.relative(repoReal, packagePath).replace(/\\/g, '/'),
            version: entry.version,
            integrity: typeof entry.integrity === 'string' ? entry.integrity : null,
          });
        }
      }
    }
  }
  return candidates.sort((left, right) => (
    left.lockRel.localeCompare(right.lockRel) || left.packageRel.localeCompare(right.packageRel)
  ));
}

function loadTypeScript(repoRoot) {
  const repoReal = fs.realpathSync(repoRoot);
  const failures = [];
  for (const candidate of lockedTypeScriptCandidates(repoReal)) {
    try {
      const packageReal = fs.realpathSync(candidate.packagePath);
      if (!isWithin(repoReal, packageReal)) throw new Error('installed package resolves outside repository');
      const packageManifestPath = path.join(packageReal, 'package.json');
      const packageManifestReal = fs.realpathSync(packageManifestPath);
      if (!isWithin(packageReal, packageManifestReal)) throw new Error('package manifest resolves outside compiler package');
      const packageManifestBytes = fs.readFileSync(packageManifestReal);
      const packageManifest = JSON.parse(packageManifestBytes.toString('utf8'));
      if (packageManifest.name !== 'typescript') throw new Error('installed package name is not typescript');
      if (packageManifest.version !== candidate.version) {
        throw new Error(`installed version ${packageManifest.version || '<missing>'} does not match lockfile version ${candidate.version}`);
      }
      const compilerPath = fs.realpathSync(path.join(packageReal, 'lib', 'typescript.js'));
      if (!isWithin(packageReal, compilerPath) || !fs.statSync(compilerPath).isFile()) {
        throw new Error('compiler entrypoint resolves outside compiler package or is not a file');
      }
      const compilerBytes = fs.readFileSync(compilerPath);
      const ts = require(compilerPath);
      if (!ts || ts.version !== candidate.version) {
        throw new Error(`compiler reports ${ts && ts.version ? ts.version : '<missing>'}, expected ${candidate.version}`);
      }
      compilerProvenance.set(ts, {
        verified: true,
        version: ts.version,
        lockfile: candidate.lockRel,
        lockfile_version: candidate.lockfileVersion,
        lockfile_sha256: candidate.lockfileSha256,
        package_path: candidate.packageRel,
        package_manifest_sha256: sha256(packageManifestBytes),
        compiler_sha256: sha256(compilerBytes),
        integrity: candidate.integrity,
      });
      return ts;
    } catch (error) {
      failures.push(`${candidate.lockRel}:${candidate.packageRel}: ${error.message}`);
    }
  }
  const suffix = failures.length ? ` Verification failures: ${failures.join('; ')}` : '';
  throw new Error(`No repository-local TypeScript compiler matched a tracked package-lock.json.${suffix}`);
}

function typescriptProvenance(ts) {
  const provenance = compilerProvenance.get(ts);
  if (!provenance) throw new Error('TypeScript compiler provenance is unavailable');
  return { ...provenance };
}

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

function sanitizeText(text) {
  let sanitized = text;

  // Redact all URI userinfo, including username-only forms, because userinfo is
  // frequently a credential and must never survive into a generated artifact.
  sanitized = sanitized.replace(
    /\b([a-z][a-z0-9+.-]{1,31}:\/\/)([^\s/?#@]+)@/gi,
    (_, scheme) => `${scheme}${REDACTED}@`,
  );
  sanitized = sanitized.replace(
    /-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----[\s\S]*?-----END(?: [A-Z0-9]+)* PRIVATE KEY-----/gi,
    REDACTED,
  );

  // Known standalone credential shapes. These are redacted regardless of the
  // surrounding identifier so a copied token in prose is still safe.
  const standaloneSecretPatterns = [
    /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g,
    /\bgh[pousr]_[A-Za-z0-9]{20,255}\b/g,
    /\bgithub_pat_[A-Za-z0-9_]{20,255}\b/g,
    /\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{16,255}\b/g,
    /\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,255}\b/g,
    /\bxox[baprs]-[A-Za-z0-9-]{10,255}\b/g,
    /\bglpat-[A-Za-z0-9_-]{16,255}\b/g,
    /\bnpm_[A-Za-z0-9]{20,255}\b/g,
    /\bhf_[A-Za-z0-9]{20,255}\b/g,
    /\bSG\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b/g,
    /\bAIza[0-9A-Za-z_-]{30,255}\b/g,
    /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
  ];
  for (const pattern of standaloneSecretPatterns) sanitized = sanitized.replace(pattern, REDACTED);

  const quotedCodeAssignment = new RegExp(
    `(\\b${SENSITIVE_LABEL}\\b\\s*(?:\\??:\\s*[^=;,\\n)]+)?\\s*=\\s*)(["'\`])((?:\\\\.|(?!\\2)[\\s\\S])*?)\\2`,
    'gi',
  );
  sanitized = sanitized.replace(
    quotedCodeAssignment,
    (_, prefix, quote) => `${prefix}${quote}${REDACTED}${quote}`,
  );

  const quotedProperty = new RegExp(
    `((?:["'])?\\b${SENSITIVE_LABEL}\\b(?:["'])?\\s*:\\s*)(["'\`])((?:\\\\.|(?!\\2)[\\s\\S])*?)\\2`,
    'gi',
  );
  sanitized = sanitized.replace(
    quotedProperty,
    (_, prefix, quote) => `${prefix}${quote}${REDACTED}${quote}`,
  );

  const quotedCliFlag = new RegExp(
    `(--${SENSITIVE_LABEL}(?:=|\\s+))(["'\`])((?:\\\\.|(?!\\2)[\\s\\S])*?)\\2`,
    'gi',
  );
  sanitized = sanitized.replace(
    quotedCliFlag,
    (_, prefix, quote) => `${prefix}${quote}${REDACTED}${quote}`,
  );

  const unquotedAssignment = new RegExp(`(\\b${SENSITIVE_LABEL}\\b\\s*=\\s*)(?!["'\`])([^\\s,;&)\\]}]+)`, 'gi');
  sanitized = sanitized.replace(unquotedAssignment, (_, prefix) => `${prefix}${REDACTED}`);

  const unquotedProperty = new RegExp(`(\\b${SENSITIVE_LABEL}\\b\\s*:\\s*)(?!["'\`])([^\\s,;})]+)`, 'gi');
  const safeTypeWords = new Set([
    'any', 'bigint', 'boolean', 'false', 'never', 'null', 'number', 'object',
    'string', 'symbol', 'true', 'undefined', 'unknown', 'void', REDACTED.toLowerCase(),
  ]);
  sanitized = sanitized.replace(unquotedProperty, (match, prefix, value) => (
    safeTypeWords.has(value.toLowerCase()) ? match : `${prefix}${REDACTED}`
  ));

  const unquotedCliFlag = new RegExp(`(--${SENSITIVE_LABEL}(?:=|\\s+))(?!["'\`])([^\\s;&]+)`, 'gi');
  sanitized = sanitized.replace(unquotedCliFlag, (_, prefix) => `${prefix}${REDACTED}`);
  sanitized = sanitized.replace(/((?:^|\s)(?:-u|--user)(?:=|\s+))([^\s;&]+)/gi, (_, prefix) => `${prefix}${REDACTED}`);

  const sensitiveQuery = new RegExp(`([?&]${SENSITIVE_LABEL}=)[^&#\\s]+`, 'gi');
  sanitized = sanitized.replace(sensitiveQuery, (_, prefix) => `${prefix}${REDACTED}`);
  sanitized = sanitized.replace(/\b((?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]{6,}/gi, (_, prefix) => `${prefix}${REDACTED}`);
  const proseSecret = new RegExp(`(\\b${SENSITIVE_LABEL}\\b\\s+(?:is|was|equals?|of)\\s+)(["']?)([^\\s,;"']{4,})(?:\\2)`, 'gi');
  sanitized = sanitized.replace(proseSecret, (_, prefix, quote) => `${prefix}${quote}${REDACTED}${quote}`);
  sanitized = sanitized.replace(
    /\b(https:\/\/(?:hooks\.slack\.com\/services|discord(?:app)?\.com\/api\/webhooks)\/)[^\s?#]+/gi,
    (_, prefix) => `${prefix}${REDACTED}`,
  );
  return sanitized;
}

function isSensitiveLabel(label) {
  if (typeof label !== 'string') return false;
  const normalized = label.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
  return new RegExp(
    `(?:^|[_-])${SENSITIVE_LABEL}s?(?:_(?:value|values|default))?$`,
    'i',
  ).test(normalized);
}

function sanitizeForOutput(value, seen = new WeakSet(), sensitiveContext = false) {
  if (typeof value === 'string') {
    if (sensitiveContext) {
      const normalized = value.trim().toLowerCase();
      const safeSentinels = new Set([
        '', 'any', 'boolean', 'false', 'missing', 'never', 'null', 'number',
        'object', 'present', 'redacted', 'string', 'true', 'undefined',
        'unknown', 'void', REDACTED.toLowerCase(),
      ]);
      if (!safeSentinels.has(normalized)) return REDACTED;
    }
    return sanitizeText(value);
  }
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value !== 'object') return sensitiveContext ? REDACTED : value;
  if (seen.has(value)) throw new Error('Cannot sanitize cyclic atlas output');
  seen.add(value);
  if (Array.isArray(value)) {
    const output = value.map((item) => sanitizeForOutput(item, seen, sensitiveContext));
    seen.delete(value);
    return output;
  }
  const output = {};
  const recordContainsSensitiveValue = [value.name, value.key, value.field, value.property, value.label]
    .some((item) => typeof item === 'string' && isSensitiveLabel(item));
  const usedKeys = new Set();
  for (const [key, item] of Object.entries(value)) {
    const keyIsSensitive = isSensitiveLabel(key);
    const valueOfSensitiveRecord = recordContainsSensitiveValue && /^(?:default|initializer|literal|value|values)$/i.test(key);
    const preserveDiscriminator = /^(?:name|key|field|property|label)$/i.test(key);
    const baseKey = sanitizeText(key);
    const keyContainsSecretShape = baseKey !== key;
    let safeKey = baseKey;
    let suffix = 2;
    while (usedKeys.has(safeKey)) {
      safeKey = `${baseKey}#sanitized-collision-${suffix}`;
      suffix += 1;
    }
    usedKeys.add(safeKey);
    output[safeKey] = sanitizeForOutput(
      item,
      seen,
      (sensitiveContext && !preserveDiscriminator) || keyIsSensitive || keyContainsSecretShape || valueOfSensitiveRecord,
    );
  }
  seen.delete(value);
  return output;
}

function trackedSourceInventory(repoRoot) {
  const raw = childProcess.execFileSync('git', ['ls-files', '-z'], { cwd: repoRoot });
  const candidates = raw
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .filter((file) => CODE_SUFFIX_RE.test(file))
    .filter((file) => !/(?:^|\/)node_modules(?:\/|$)/.test(file))
    .sort();
  const files = [];
  const skippedSecretPaths = [];
  const skippedNonregularPaths = [];
  for (const file of candidates) {
    if (isSecretClassifiedPath(file)) {
      skippedSecretPaths.push(file);
      continue;
    }
    const absolute = path.resolve(repoRoot, file);
    let fileStat;
    try {
      fileStat = fs.lstatSync(absolute);
    } catch (_) {
      skippedNonregularPaths.push({ path: file, path_kind: 'missing' });
      continue;
    }
    if (!fileStat.isFile()) {
      skippedNonregularPaths.push({
        path: file,
        path_kind: fileStat.isSymbolicLink() ? 'symlink' : 'nonregular',
      });
      continue;
    }
    files.push(file);
  }
  return { files, skippedSecretPaths, skippedNonregularPaths };
}

function lineOf(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
}

function endLineOf(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getEnd()).line + 1;
}

function sourceSpan(sourceFile, node) {
  const startOffset = node.getStart(sourceFile);
  const endOffset = node.getEnd();
  const start = sourceFile.getLineAndCharacterOfPosition(startOffset);
  const end = sourceFile.getLineAndCharacterOfPosition(endOffset);
  return {
    line: start.line + 1,
    column: start.character,
    end_line: end.line + 1,
    end_column: end.character,
    start_offset: startOffset,
    end_offset: endOffset,
  };
}

function nodeText(sourceFile, node, limit = 600) {
  if (!node) return null;
  return node.getText(sourceFile).replace(/\s+/g, ' ').slice(0, limit);
}

function nameText(sourceFile, node, fallback) {
  if (!node) return fallback;
  return nodeText(sourceFile, node, 300) || fallback;
}

function stringValue(ts, node) {
  if (!node) return null;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text;
    for (const span of node.templateSpans) {
      value += `{${nodeText(node.getSourceFile(), span.expression, 120) || 'expr'}}${span.literal.text}`;
    }
    return value;
  }
  return null;
}

function propertyName(ts, sourceFile, node) {
  if (!node) return null;
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text;
  if (ts.isStringLiteral(node) || ts.isNumericLiteral(node)) return node.text;
  return nodeText(sourceFile, node, 200);
}

function callTarget(ts, sourceFile, expression) {
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression)) return nodeText(sourceFile, expression, 300);
  if (ts.isElementAccessExpression(expression)) return nodeText(sourceFile, expression, 300);
  return nodeText(sourceFile, expression, 300) || '<dynamic>';
}

function modifiersOf(ts, node) {
  const modifiers = typeof ts.getModifiers === 'function' ? ts.getModifiers(node) : node.modifiers;
  return (modifiers || []).map((item) => item.getText(node.getSourceFile()));
}

function jsDocSummary(ts, node) {
  const docs = node.jsDoc || [];
  for (const doc of docs) {
    if (typeof doc.comment === 'string' && doc.comment.trim()) return doc.comment.trim().split('\n')[0].slice(0, 500);
  }
  return null;
}

function contractFields(ts, sourceFile, members) {
  const fields = [];
  for (const member of members || []) {
    if (
      ts.isPropertySignature(member) ||
      ts.isPropertyDeclaration(member) ||
      ts.isMethodSignature(member) ||
      ts.isMethodDeclaration(member)
    ) {
      fields.push({
        name: propertyName(ts, sourceFile, member.name),
        kind: ts.SyntaxKind[member.kind],
        optional: Boolean(member.questionToken),
        readonly: modifiersOf(ts, member).includes('readonly'),
        annotation: member.type ? nodeText(sourceFile, member.type, 500) : null,
        ...sourceSpan(sourceFile, member),
      });
    }
  }
  return fields;
}

function functionSignature(ts, sourceFile, node, name) {
  const params = (node.parameters || []).map((param) => nodeText(sourceFile, param, 300)).join(', ');
  const returnType = node.type ? `: ${nodeText(sourceFile, node.type, 300)}` : '';
  return `${name}(${params})${returnType}`.slice(0, 1200);
}

function extractFile(ts, repoRoot, relPath) {
  if (isSecretClassifiedPath(relPath)) {
    throw new Error(`Refusing to read secret-classified source path: ${relPath}`);
  }
  const repoReal = fs.realpathSync(repoRoot);
  const absolute = path.resolve(repoReal, relPath);
  if (!isWithin(repoReal, absolute)) {
    throw new Error(`Refusing to read source path outside repository: ${relPath}`);
  }
  const pathStat = fs.lstatSync(absolute);
  if (!pathStat.isFile()) {
    throw new Error(`Refusing to follow nonregular source path: ${relPath}`);
  }
  const noFollow = fs.constants.O_NOFOLLOW || 0;
  const descriptor = fs.openSync(absolute, fs.constants.O_RDONLY | noFollow);
  let source;
  try {
    if (!fs.fstatSync(descriptor).isFile()) {
      throw new Error(`Refusing to read non-file descriptor for source path: ${relPath}`);
    }
    source = fs.readFileSync(descriptor, 'utf8');
  } finally {
    fs.closeSync(descriptor);
  }
  const extension = path.extname(relPath).toLowerCase();
  const scriptKind = extension === '.tsx'
    ? ts.ScriptKind.TSX
    : extension === '.jsx'
      ? ts.ScriptKind.JSX
      : extension === '.js' || extension === '.mjs' || extension === '.cjs'
        ? ts.ScriptKind.JS
        : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(relPath, source, ts.ScriptTarget.Latest, true, scriptKind);
  const symbols = [];
  const contracts = [];
  const imports = [];
  const calls = [];
  const envReferences = [];
  const apiReferences = [];
  const routeDefinitions = [];
  const scope = [];
  const symbolStack = [];
  const apiReferenceKeys = new Set();
  const semanticallyClassifiedApiNodes = new Set();

  function currentSymbolId() {
    return symbolStack.length ? symbolStack[symbolStack.length - 1] : `${relPath}:<module>`;
  }

  symbols.push({
    symbol_id: `${relPath}:<module>`,
    path: relPath,
    qualname: '<module>',
    kind: 'module',
    line_start: 1,
    line_end: sourceFile.getLineAndCharacterOfPosition(sourceFile.getEnd()).line + 1,
    signature: null,
    modifiers: [],
    doc: null,
    parser_confidence: 'compiler_ast',
  });

  function addSymbol(node, kind, localName, signature) {
    const safeName = localName || `<anonymous@${lineOf(sourceFile, node)}>`;
    const qualname = [...scope, safeName].join('.');
    const symbolId = `${relPath}:${qualname}@${lineOf(sourceFile, node)}`;
    symbols.push({
      symbol_id: symbolId,
      path: relPath,
      qualname,
      kind,
      line_start: lineOf(sourceFile, node),
      line_end: endLineOf(sourceFile, node),
      signature: signature || nodeText(sourceFile, node, 1200),
      modifiers: modifiersOf(ts, node),
      doc: jsDocSummary(ts, node),
      parser_confidence: 'compiler_ast',
    });
    return { symbolId, safeName };
  }

  function addApiReference(node, route, kind, method = null) {
    if (!route || !route.startsWith('/')) return false;
    const key = `${node.pos}:${node.end}\0${route}\0${kind}\0${method || ''}`;
    if (apiReferenceKeys.has(key)) return false;
    apiReferenceKeys.add(key);
    apiReferences.push({
      path: route,
      method,
      kind,
      source_path: relPath,
      ...sourceSpan(sourceFile, node),
      symbol_id: currentSymbolId(),
    });
    return true;
  }

  function visit(node) {
    if (ts.isImportDeclaration(node)) {
      const module = stringValue(ts, node.moduleSpecifier);
      const names = [];
      if (node.importClause) {
        if (node.importClause.name) names.push({ imported: 'default', local: node.importClause.name.text });
        const bindings = node.importClause.namedBindings;
        if (bindings && ts.isNamespaceImport(bindings)) names.push({ imported: '*', local: bindings.name.text });
        if (bindings && ts.isNamedImports(bindings)) {
          for (const item of bindings.elements) {
            names.push({ imported: item.propertyName ? item.propertyName.text : item.name.text, local: item.name.text });
          }
        }
      }
      imports.push({ module, names, line: lineOf(sourceFile, node), kind: 'import' });
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      imports.push({ module: stringValue(ts, node.moduleSpecifier), names: [], line: lineOf(sourceFile, node), kind: 're_export' });
    }

    if (ts.isInterfaceDeclaration(node)) {
      const name = node.name.text;
      const added = addSymbol(node, 'interface', name, nodeText(sourceFile, node, 1200));
      contracts.push({
        contract_id: added.symbolId,
        path: relPath,
        name: [...scope, name].join('.'),
        kind: 'typescript_interface',
        fields: contractFields(ts, sourceFile, node.members),
        line_start: lineOf(sourceFile, node),
        line_end: endLineOf(sourceFile, node),
        parser_confidence: 'compiler_ast',
      });
    } else if (ts.isTypeAliasDeclaration(node)) {
      const name = node.name.text;
      const added = addSymbol(node, 'type_alias', name, nodeText(sourceFile, node, 1200));
      const fields = ts.isTypeLiteralNode(node.type) ? contractFields(ts, sourceFile, node.type.members) : [];
      contracts.push({
        contract_id: added.symbolId,
        path: relPath,
        name: [...scope, name].join('.'),
        kind: 'typescript_type_alias',
        expression: nodeText(sourceFile, node.type, 1500),
        fields,
        line_start: lineOf(sourceFile, node),
        line_end: endLineOf(sourceFile, node),
        parser_confidence: 'compiler_ast',
      });
    } else if (ts.isEnumDeclaration(node)) {
      const name = node.name.text;
      const added = addSymbol(node, 'enum', name, nodeText(sourceFile, node, 1200));
      contracts.push({
        contract_id: added.symbolId,
        path: relPath,
        name: [...scope, name].join('.'),
        kind: 'typescript_enum',
        fields: node.members.map((member) => ({
          name: propertyName(ts, sourceFile, member.name),
          value: member.initializer ? nodeText(sourceFile, member.initializer, 300) : null,
          ...sourceSpan(sourceFile, member),
        })),
        line_start: lineOf(sourceFile, node),
        line_end: endLineOf(sourceFile, node),
        parser_confidence: 'compiler_ast',
      });
    }

    let pushedScope = false;
    let pushedSymbol = false;
    if (ts.isClassDeclaration(node)) {
      const name = node.name ? node.name.text : `<anonymous_class@${lineOf(sourceFile, node)}>`;
      const added = addSymbol(node, 'class', name, nodeText(sourceFile, node, 1200));
      contracts.push({
        contract_id: added.symbolId,
        path: relPath,
        name: [...scope, name].join('.'),
        kind: 'typescript_class',
        fields: contractFields(ts, sourceFile, node.members),
        line_start: lineOf(sourceFile, node),
        line_end: endLineOf(sourceFile, node),
        parser_confidence: 'compiler_ast',
      });
      scope.push(name);
      symbolStack.push(added.symbolId);
      pushedScope = true;
      pushedSymbol = true;
    } else if (ts.isFunctionDeclaration(node)) {
      const name = node.name ? node.name.text : `<anonymous@${lineOf(sourceFile, node)}>`;
      const added = addSymbol(node, 'function', name, functionSignature(ts, sourceFile, node, name));
      scope.push(name);
      symbolStack.push(added.symbolId);
      pushedScope = true;
      pushedSymbol = true;
    } else if (ts.isMethodDeclaration(node) || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) {
      const name = propertyName(ts, sourceFile, node.name) || `<method@${lineOf(sourceFile, node)}>`;
      const kind = ts.isGetAccessorDeclaration(node) ? 'getter' : ts.isSetAccessorDeclaration(node) ? 'setter' : 'method';
      const added = addSymbol(node, kind, name, functionSignature(ts, sourceFile, node, name));
      scope.push(name);
      symbolStack.push(added.symbolId);
      pushedScope = true;
      pushedSymbol = true;
    } else if (ts.isConstructorDeclaration(node)) {
      const name = 'constructor';
      const added = addSymbol(node, 'constructor', name, functionSignature(ts, sourceFile, node, name));
      scope.push(name);
      symbolStack.push(added.symbolId);
      pushedScope = true;
      pushedSymbol = true;
    } else if (ts.isVariableDeclaration(node) && node.initializer && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) {
      const name = nameText(sourceFile, node.name, `<arrow@${lineOf(sourceFile, node)}>`);
      const added = addSymbol(node, ts.isArrowFunction(node.initializer) ? 'arrow_function' : 'function_expression', name, functionSignature(ts, sourceFile, node.initializer, name));
      scope.push(name);
      symbolStack.push(added.symbolId);
      pushedScope = true;
      pushedSymbol = true;
    }

    if (ts.isCallExpression(node)) {
      const target = callTarget(ts, sourceFile, node.expression);
      calls.push({
        caller_symbol_id: currentSymbolId(),
        raw_call: target,
        ...sourceSpan(sourceFile, node),
        argument_count: node.arguments.length,
      });
      const firstNode = node.arguments.length ? node.arguments[0] : null;
      const first = firstNode ? stringValue(ts, firstNode) : null;
      const method = target.split('.').pop().toUpperCase();
      let classifiedApiArgument = false;
      if (target === 'fetch' && first) {
        classifiedApiArgument = addApiReference(firstNode, first, 'fetch', null);
      } else if (first && /^\/api\/(?:v1|v2)\//.test(first)) {
        classifiedApiArgument = addApiReference(
          firstNode,
          first,
          'client_call',
          ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method) ? method : null,
        );
      }
      if (classifiedApiArgument) semanticallyClassifiedApiNodes.add(`${firstNode.pos}:${firstNode.end}`);
      if (target.endsWith('.route') || target.endsWith('.createBrowserRouter')) {
        if (first) routeDefinitions.push({ path: first, source_path: relPath, ...sourceSpan(sourceFile, node), symbol_id: currentSymbolId() });
      }
    }

    if (ts.isPropertyAccessExpression(node)) {
      const rendered = nodeText(sourceFile, node, 500);
      const envMatch = rendered && rendered.match(/^(?:import\.meta\.env|process\.env)\.([A-Z][A-Z0-9_]+)$/);
      if (envMatch) {
        envReferences.push({ key: envMatch[1], path: relPath, ...sourceSpan(sourceFile, node), symbol_id: currentSymbolId(), default: { state: 'unknown' } });
      }
    }

    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      const value = node.text;
      const nodeIdentity = `${node.pos}:${node.end}`;
      if (/^\/api\/(?:v1|v2)\//.test(value) && !semanticallyClassifiedApiNodes.has(nodeIdentity)) {
        addApiReference(node, value, 'string_reference', null);
      }
    }

    ts.forEachChild(node, visit);
    if (pushedSymbol) symbolStack.pop();
    if (pushedScope) scope.pop();
  }

  visit(sourceFile);
  const diagnostics = sourceFile.parseDiagnostics.map((diag) => ({
    code: diag.code,
    message: ts.flattenDiagnosticMessageText(diag.messageText, '\n'),
    start: diag.start,
  }));
  return sanitizeForOutput({
    path: relPath,
    sha256: sha256(source),
    line_count: sourceFile.getLineAndCharacterOfPosition(sourceFile.getEnd()).line + 1,
    parser: 'typescript_compiler_ast',
    parse_diagnostics: diagnostics,
    imports,
    symbols,
    contracts,
    calls,
    env_references: envReferences,
    api_references: apiReferences,
    route_definitions: routeDefinitions,
  });
}

function build(repoRoot, outputPath) {
  const ts = loadTypeScript(repoRoot);
  const provenance = typescriptProvenance(ts);
  const inventory = trackedSourceInventory(repoRoot);
  const files = inventory.files;
  const modules = files.map((file) => extractFile(ts, repoRoot, file));
  const revalidatedTs = loadTypeScript(repoRoot);
  const provenanceEnd = typescriptProvenance(revalidatedTs);
  const compilerSnapshotConsistent = JSON.stringify(provenance) === JSON.stringify(provenanceEnd);
  const result = {
    metadata: {
      schema_version: 1,
      generated_at: new Date().toISOString(),
      parser: `typescript@${ts.version}`,
      tracked_source_files: files.length,
      secret_paths_excluded: inventory.skippedSecretPaths,
      nonregular_source_paths_excluded: inventory.skippedNonregularPaths,
      typescript_compiler: provenance,
      typescript_compiler_end: provenanceEnd,
      typescript_compiler_snapshot_consistent: compilerSnapshotConsistent,
    },
    modules,
    symbols: modules.flatMap((module) => module.symbols),
    contracts: modules.flatMap((module) => module.contracts),
    calls: modules.flatMap((module) => module.calls),
    imports: modules.flatMap((module) => module.imports.map((item) => ({ ...item, path: module.path }))),
    env_references: modules.flatMap((module) => module.env_references),
    api_references: modules.flatMap((module) => module.api_references),
    route_definitions: modules.flatMap((module) => module.route_definitions),
    parse_diagnostics: modules.flatMap((module) => module.parse_diagnostics.map((item) => ({ ...item, path: module.path }))),
  };
  const safeResult = sanitizeForOutput(result);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(safeResult)}\n`, 'utf8');
  return safeResult;
}

function selfTest(repoRoot) {
  const ts = loadTypeScript(repoRoot);
  const provenance = typescriptProvenance(ts);
  if (!provenance.verified || provenance.version !== ts.version || !provenance.lockfile) {
    throw new Error('compiler lockfile verification failed');
  }
  if (!isSecretClassifiedPath('secrets/fixture.ts') || !isSecretClassifiedPath('v2/.env.ts')) {
    throw new Error('secret path classification failed');
  }
  const tempRoot = fs.mkdtempSync(path.join(require('os').tmpdir(), 'atlas-ts-'));
  const rel = 'fixture.tsx';
  const fakePassword = ['atlas', 'Fake', 'Password', '934!'].join('');
  const fakeGitHubToken = ['ghp_', 'A'.repeat(32)].join('');
  const fakeAwsAccessKey = ['AKIA', 'B'.repeat(16)].join('');
  const fakeJwt = [`eyJ${'C'.repeat(12)}`, `eyJ${'D'.repeat(12)}`, `E${'F'.repeat(12)}`].join('.');
  const fakeUri = `https://atlas-user:${fakePassword}@example.invalid/private`;
  const fakePrivateKey = ['-----BEGIN PRIVATE KEY-----', 'ATLAS-TEST-ONLY', '-----END PRIVATE KEY-----'].join('\n');
  const fakeCommand = `curl --token ${fakeGitHubToken} -H "Authorization: Bearer ${fakeJwt}" ${fakeUri}`;
  const fakeOpaqueDefault = ['opaque', 'Default', 'Value', '731'].join('');
  const boundaryFixture = sanitizeForOutput({
    name: 'clientSecret',
    default: fakeOpaqueDefault,
    signature: `function demo(apiKey: string = ${JSON.stringify(fakeOpaqueDefault)}): string`,
    doc: `credential is ${fakeOpaqueDefault}`,
    command: fakeCommand,
    uri: fakeUri,
  });
  const contextualFixture = sanitizeForOutput({
    record: { name: 'ConfigEntry', key: 'api_token', value: fakeOpaqueDefault },
    numeric: { api_token: 731934 },
    tokens: [fakeOpaqueDefault],
    credentials: [{ label: 'opaque', value: fakeOpaqueDefault }],
    secretShapedKey: {
      [fakeGitHubToken]: fakeOpaqueDefault,
      [fakeAwsAccessKey]: fakeOpaqueDefault,
      [`${REDACTED}#sanitized-collision-2`]: 'benign-third-value',
    },
    benignMetadata: { signature: 'sha256', token_count: 812345 },
  });
  const boundaryFixtureText = JSON.stringify({ boundaryFixture, contextualFixture });
  if (boundaryFixtureText.includes(fakeOpaqueDefault) || boundaryFixtureText.includes(fakeUri) || boundaryFixtureText.includes(fakeGitHubToken)) {
    throw new Error('direct output-boundary sanitization failed');
  }
  if (boundaryFixture.signature === REDACTED || !boundaryFixture.signature.includes(REDACTED)) {
    throw new Error('signature boundary sanitization lost structural text');
  }
  if (contextualFixture.benignMetadata.signature !== 'sha256' || contextualFixture.benignMetadata.token_count !== 812345) {
    throw new Error('benign token/signature metadata was over-redacted');
  }
  if (Object.keys(contextualFixture.secretShapedKey).length !== 3) {
    throw new Error('sanitized object-key collision dropped a record');
  }
  try {
    extractFile(ts, tempRoot, 'secrets/does-not-exist.ts');
    throw new Error('secret-classified path was accepted');
  } catch (error) {
    if (!String(error.message).startsWith('Refusing to read secret-classified source path:')) throw error;
  }
  const source = [
    "import React from 'react';",
    'interface Quote { event_time: string; price: number }',
    'interface DuplicateFields { value: string; value: number }',
    `enum CredentialFixture { API_TOKEN = ${JSON.stringify(fakeGitHubToken)}, AWS_ACCESS_KEY = ${JSON.stringify(fakeAwsAccessKey)} }`,
    `/** operator password=${fakePassword}; upstream=${fakeUri} */`,
    `class Vault { password: string = ${JSON.stringify(fakePassword)}; command = ${JSON.stringify(fakeCommand)}; privateKey = ${JSON.stringify(fakePrivateKey)}; }`,
    `function connect(password: string = ${JSON.stringify(fakePassword)}, endpoint: string = ${JSON.stringify(fakeUri)}): string { return endpoint; }`,
    'declare const client: { get(path: string): Promise<Quote> };',
    "const endpoint = import.meta.env.VITE_API_BASE_URL;",
    "const documentedRoute = '/api/v2/quote';",
    "export const load = async (): Promise<Quote> => fetch('/api/v2/quote').then((r) => r.json());",
    "export const loadTrades = async (): Promise<Quote> => client.get('/api/v2/trades');",
    'export function Card({ price }: Quote) { return <div>{price}</div>; }',
  ].join('\n');
  try {
    fs.writeFileSync(path.join(tempRoot, rel), source, 'utf8');
    const symlinkRel = 'fixture-link.ts';
    fs.symlinkSync(rel, path.join(tempRoot, symlinkRel));
    try {
      extractFile(ts, tempRoot, symlinkRel);
      throw new Error('tracked-style source symlink was followed');
    } catch (error) {
      if (!String(error.message).startsWith('Refusing to follow nonregular source path:')) throw error;
    }
    const parsed = extractFile(ts, tempRoot, rel);
    const names = new Set(parsed.symbols.map((item) => item.qualname));
    if (!names.has('Quote') || !names.has('load') || !names.has('Card') || !names.has('Vault') || !names.has('connect')) {
      throw new Error('symbol extraction failed');
    }
    if (!parsed.contracts.some((item) => item.name === 'Quote' && item.fields.some((field) => field.name === 'event_time'))) {
      throw new Error('contract extraction failed');
    }
    const duplicateFields = parsed.contracts
      .find((item) => item.name === 'DuplicateFields')
      ?.fields.filter((field) => field.name === 'value') || [];
    if (duplicateFields.length !== 2 || new Set(duplicateFields.map((field) => field.start_offset)).size !== 2) {
      throw new Error('same-line contract-field source spans are not distinct');
    }
    if (!parsed.env_references.some((item) => item.key === 'VITE_API_BASE_URL')) throw new Error('env extraction failed');

    const quoteRefs = parsed.api_references.filter((item) => item.path === '/api/v2/quote');
    if (quoteRefs.length !== 2 || quoteRefs.filter((item) => item.kind === 'fetch').length !== 1 || quoteRefs.filter((item) => item.kind === 'string_reference').length !== 1) {
      throw new Error('fetch/string API reference deduplication failed');
    }
    const tradeRefs = parsed.api_references.filter((item) => item.path === '/api/v2/trades');
    if (tradeRefs.length !== 1 || tradeRefs[0].kind !== 'client_call' || tradeRefs[0].method !== 'GET') {
      throw new Error('client API reference classification failed');
    }
    const spannedRecords = [...parsed.calls, ...parsed.api_references];
    if (!spannedRecords.length || spannedRecords.some((item) => (
      !Number.isInteger(item.line) || !Number.isInteger(item.column) ||
      !Number.isInteger(item.end_line) || !Number.isInteger(item.end_column) ||
      !Number.isInteger(item.start_offset) || !Number.isInteger(item.end_offset) ||
      item.end_offset < item.start_offset
    ))) {
      throw new Error('call/API source span extraction failed');
    }

    const serialized = JSON.stringify(parsed);
    for (const forbidden of [fakePassword, fakeGitHubToken, fakeAwsAccessKey, fakeJwt, fakeUri, fakePrivateKey, 'atlas-user:']) {
      if (serialized.includes(forbidden)) throw new Error(`secret boundary sanitization failed for ${sha256(forbidden).slice(0, 12)}`);
    }
    if (!serialized.includes(REDACTED)) throw new Error('redaction marker missing');
    const vault = parsed.symbols.find((item) => item.qualname === 'Vault');
    const connect = parsed.symbols.find((item) => item.qualname === 'connect');
    const enumContract = parsed.contracts.find((item) => item.name === 'CredentialFixture');
    if (!vault || !vault.signature.includes(REDACTED) || !vault.doc.includes(REDACTED)) {
      throw new Error('class text or documentation sanitization failed');
    }
    if (!connect || !connect.signature.includes(REDACTED)) throw new Error('default/signature sanitization failed');
    if (!enumContract || enumContract.fields.some((field) => field.value && !field.value.includes(REDACTED))) {
      throw new Error('enum initializer sanitization failed');
    }
    return {
      ok: true,
      symbols: parsed.symbols.length,
      contracts: parsed.contracts.length,
      api_references: parsed.api_references.length,
      compiler: provenance,
    };
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const repoRoot = path.resolve(args['repo-root'] || path.join(__dirname, '..'));
  if (args.selfTest) {
    process.stdout.write(`${JSON.stringify(selfTest(repoRoot), null, 2)}\n`);
    return;
  }
  if (!args.out) throw new Error('--out is required');
  const result = build(repoRoot, path.resolve(args.out));
  process.stdout.write(`${JSON.stringify({ files: result.modules.length, symbols: result.symbols.length, contracts: result.contracts.length })}\n`);
}

if (require.main === module) main();

module.exports = {
  extractFile,
  isSecretClassifiedPath,
  loadTypeScript,
  sanitizeForOutput,
  selfTest,
  typescriptProvenance,
};
