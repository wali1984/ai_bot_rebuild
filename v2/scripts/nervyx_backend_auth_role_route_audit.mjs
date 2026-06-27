import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const repoRoot = path.resolve(scriptDir, '..');
const rebuildRoot = path.resolve(repoRoot, '..');
const artifactRoot = path.join(repoRoot, 'artifacts');
const frontendDistIndex = path.join(repoRoot, 'frontend', 'dist', 'index.html');
const frontendMode = process.env.NERVYX_ROLE_ROUTE_AUDIT_FRONTEND === 'vite' ? 'vite' : 'backend_spa';
const runtimeRoot = path.join(
  artifactRoot,
  'nervyx-backend-auth-role-route-audit-runtime',
  new Date().toISOString().replace(/[:.]/g, '-'),
);
const python = fs.existsSync(path.join(rebuildRoot, '.venv', 'bin', 'python'))
  ? path.join(rebuildRoot, '.venv', 'bin', 'python')
  : 'python3';

function auditPassword(role) {
  return `Audit${role[0].toUpperCase()}${role.slice(1)}2026!${crypto.randomBytes(8).toString('hex')}Aa1`;
}

const users = {
  viewer: { email: 'viewer.audit@nervyx.local', password: auditPassword('viewer') },
  trader: { email: 'trader.audit@nervyx.local', password: auditPassword('trader') },
  admin: { email: 'admin.audit@nervyx.local', password: auditPassword('admin') },
  superadmin: { email: 'superadmin.audit@nervyx.local', password: auditPassword('superadmin') },
};

const children = new Set();

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : null;
      server.close(() => {
        if (!port) reject(new Error('Could not allocate a local port'));
        else resolve(port);
      });
    });
  });
}

function spawnLogged(command, args, options = {}) {
  const child = spawn(command, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options,
  });
  children.add(child);
  child.stdout.on('data', (chunk) => process.stdout.write(chunk));
  child.stderr.on('data', (chunk) => process.stderr.write(chunk));
  child.on('exit', () => children.delete(child));
  return child;
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawnLogged(command, args, options);
    child.on('error', reject);
    child.on('exit', (code, signal) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(' ')} exited with code ${code ?? 'null'} signal ${signal ?? 'null'}`));
      }
    });
  });
}

async function waitForHttp(url, acceptedStatuses, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { cache: 'no-store' });
      if (acceptedStatuses.includes(response.status)) return response.status;
      lastError = new Error(`${url} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
}

async function stopChildren() {
  const running = Array.from(children).filter((child) => child.exitCode === null && child.signalCode === null);
  for (const child of running) child.kill('SIGTERM');
  await new Promise((resolve) => setTimeout(resolve, 1500));
  for (const child of running) {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }
}

function serviceEnv(extra = {}) {
  return {
    ...process.env,
    PYTHONPATH: path.join(repoRoot, 'backend'),
    V2_REPO_ROOT: rebuildRoot,
    ALPHAFORGE_ENV: 'development',
    ALPHAFORGE_AUTH_STORE: path.join(runtimeRoot, 'auth_users.json'),
    ALPHAFORGE_AUTH_REVOCATION_STORE: path.join(runtimeRoot, 'auth_revocations.json'),
    ALPHAFORGE_AUTH_SECRET: `nervyx-role-route-audit-${crypto.randomBytes(32).toString('hex')}`,
    ALPHAFORGE_AUTH_COOKIE_SAMESITE: 'lax',
    ALPHAFORGE_AUTH_COOKIE_SECURE: 'false',
    ALPHAFORGE_SEED_INITIAL_TRADER: 'false',
    ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL: '',
    ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD: '',
    ...extra,
  };
}

async function seedUsers(env) {
  const seedScript = `
import json
from app.auth.users import UserStore

users = json.loads(${JSON.stringify(JSON.stringify(users))})
store = UserStore()
seed = [
    {
        "role": "viewer",
        "email": users["viewer"]["email"],
        "username": "audit_viewer",
        "password": users["viewer"]["password"],
        "watchlist": ["BTCUSDT", "ETHUSDT"],
    },
    {
        "role": "trader",
        "email": users["trader"]["email"],
        "username": "audit_trader",
        "password": users["trader"]["password"],
        "trader_id": "audit-trader",
        "paper_account_id": "audit-paper-account",
        "exchange_accounts": [{
            "id": "audit-binance-readonly",
            "exchange": "binance",
            "label": "Audit Binance Futures Readonly",
            "account_type": "usd_m_futures",
            "mode": "read_only",
            "read_only": True,
            "live_trading_enabled": False,
            "status": "credential_source_pending",
        }],
        "watchlist": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    },
    {
        "role": "admin",
        "email": users["admin"]["email"],
        "username": "audit_admin",
        "password": users["admin"]["password"],
        "watchlist": ["BTCUSDT", "ETHUSDT"],
    },
    {
        "role": "superadmin",
        "email": users["superadmin"]["email"],
        "username": "audit_superadmin",
        "password": users["superadmin"]["password"],
        "watchlist": ["BTCUSDT", "ETHUSDT"],
    },
]
for user in seed:
    store.create_user(
        email=user["email"],
        username=user["username"],
        password=user["password"],
        role=user["role"],
        trader_id=user.get("trader_id"),
        paper_account_id=user.get("paper_account_id"),
        exchange_accounts=user.get("exchange_accounts"),
        watchlist=user.get("watchlist"),
        is_active=True,
    )
print(json.dumps({"seeded_roles": sorted(users.keys())}))
`;
  await run(python, ['-c', seedScript], { cwd: repoRoot, env });
}

async function main() {
  fs.mkdirSync(runtimeRoot, { recursive: true });
  const backendPort = await getFreePort();
  const frontendPort = frontendMode === 'vite' ? await getFreePort() : null;
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const frontendUrl = frontendMode === 'vite' ? `http://127.0.0.1:${frontendPort}` : backendUrl;
  const env = serviceEnv();

  console.log(`Backend-auth route audit runtime: ${runtimeRoot}`);
  console.log(`Backend: ${backendUrl}`);
  console.log(`Frontend: ${frontendUrl} (${frontendMode})`);

  await seedUsers(env);

  if (frontendMode === 'backend_spa' && !fs.existsSync(frontendDistIndex)) {
    await run('npm', ['run', '--prefix', 'frontend', 'build'], { cwd: repoRoot, env: serviceEnv() });
  }

  const backend = spawnLogged(
    python,
    ['-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', String(backendPort)],
    { cwd: path.join(repoRoot, 'backend'), env },
  );
  backend.on('exit', (code, signal) => {
    if (code !== null && code !== 0) console.error(`Backend exited with ${code} ${signal ?? ''}`);
  });
  await waitForHttp(`${backendUrl}/api/health`, [200], 60_000);

  if (frontendMode === 'vite') {
    const frontend = spawnLogged(
      'npm',
      ['run', '--prefix', 'frontend', 'dev', '--', '--host', '127.0.0.1', '--port', String(frontendPort)],
      {
        cwd: repoRoot,
        env: serviceEnv({
          CHOKIDAR_USEPOLLING: 'true',
          VITE_API_PROXY_TARGET: backendUrl,
        }),
      },
    );
    frontend.on('exit', (code, signal) => {
      if (code !== null && code !== 0) console.error(`Frontend exited with ${code} ${signal ?? ''}`);
    });
  }
  await waitForHttp(frontendUrl, [200], 60_000);

  await run(
    'npm',
    ['run', '--prefix', 'frontend', 'test:e2e', '--', 'nervyx_role_route_audit.spec.ts', '--project=chromium'],
    {
      cwd: repoRoot,
      env: serviceEnv({
        PLAYWRIGHT_NO_WEBSERVER: '1',
        PLAYWRIGHT_BASE_URL: frontendUrl,
        NERVYX_ROLE_ROUTE_AUTH_MODE: 'backend_login',
        NERVYX_ROLE_ROUTE_AUTH_USERS: JSON.stringify(users),
      }),
    },
  );

  const artifactPath = path.join(artifactRoot, 'nervyx-role-route-audit-backend-auth.json');
  const artifact = JSON.parse(fs.readFileSync(artifactPath, 'utf8'));
  console.log(JSON.stringify({
    artifact: path.relative(repoRoot, artifactPath),
    status: artifact.status,
    auth_backend_login_gate_proven: artifact.auth_backend_login_gate_proven,
    summary: artifact.summary,
  }, null, 2));
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await stopChildren();
  });
