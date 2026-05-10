import type { PageMeta, PageRbac, PageRoute } from '../../types/page';
import { DangerousControlPanel } from '../controls/DangerousControlPanel';

interface Props {
  meta: PageMeta;
  rbac: PageRbac;
  route: PageRoute;
}

export function PageShell({ meta, rbac, route }: Props): JSX.Element {
  return (
    <article
      className="page-shell"
      data-testid={`page-${meta.id}`}
      data-page-id={meta.id}
      data-page-surface={meta.surface}
      data-page-min-role={rbac.minRole}
      data-page-path={route.path}
    >
      <header className="page-shell__header">
        <h1>{meta.title}</h1>
        <p className="page-shell__description">{meta.description}</p>
      </header>
      <DangerousControlPanel controlIds={meta.dangerousControlIds} />
      <section className="page-shell__body">
        <p className="cockpit-evidence-gap">
          Evidence missing - this route is registered but needs a dedicated data
          payload before it can be used for live-readiness decisions.
        </p>
      </section>
    </article>
  );
}
