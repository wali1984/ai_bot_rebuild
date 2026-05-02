import meta from './meta';
import rbac from './rbac';
import route from './route';
import { PageShell } from '../../components/layout/PageShell';
export default function SystemHealthPage(): JSX.Element {
  return <PageShell meta={meta} rbac={rbac} route={route} />;
}
