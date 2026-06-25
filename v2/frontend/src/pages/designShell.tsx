import type { ReactNode } from 'react';
import { DangerousControlPanel } from '../components/controls/DangerousControlPanel';
import type { PageMeta, PageRbac, PageRoute } from '../types/page';
import { Panel } from './cockpitComponents';

const LIVE_BLOCKED = 'EXECUTION ROUTING: operator gated';

interface DesignPageShellProps {
  meta: PageMeta;
  rbac: PageRbac;
  route: PageRoute;
  eyebrow: string;
  source: string;
  children: ReactNode;
  status?: string;
}

export function DesignPageShell({ meta, rbac, route, eyebrow, source, status = 'NON-LIVE OPERATOR SURFACE', children }: DesignPageShellProps): JSX.Element {
  return (
    <article
      className="enterprise-cockpit-page design-page-shell grid-bg"
      data-testid={`page-${meta.id}`}
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="design-page-hero panel bracketed hatch" data-testid={`design-hero-${meta.id}`}>
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <div className="design-page-hero__copy">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="design-page-hero__ribbons" aria-label="Page safety and data source">
          <span className="chip solid-block">{LIVE_BLOCKED}</span>
          <span className="chip solid-paper">{status}</span>
          <span className="chip">{source}</span>
        </div>
      </header>
      <DangerousControlPanel controlIds={meta.dangerousControlIds} />
      {children}
    </article>
  );
}

export function EvidenceGapPanel({ id, title, missingSource, children }: { id: string; title: string; missingSource: string; children?: ReactNode }): JSX.Element {
  return (
    <Panel id={id} title={title} right={<span className="chip solid-warn">MISSING_EVIDENCE</span>}>
      <p className="cockpit-evidence-gap">
        Evidence missing - cannot explain without guessing. Missing source: {missingSource}
      </p>
      {children}
    </Panel>
  );
}

export function SourceRibbon({ labels }: { labels: string[] }): JSX.Element {
  return (
    <div className="design-source-ribbon" aria-label="Data source classifications">
      {labels.map((label) => (
        <span className="chip" key={label}>{label}</span>
      ))}
    </div>
  );
}
