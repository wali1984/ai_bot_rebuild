import { Link } from 'react-router-dom';
import '../../pages/login/authPages.css';

export function AccessDenied({ required = 'admin' }: { required?: string }): JSX.Element {
  return (
    <main className="auth-state-page" data-testid="access-denied">
      <section className="auth-state-card">
        <span className="auth-state-card__eyebrow">Access denied</span>
        <h1>Backend role required</h1>
        <p>This page requires a backend-confirmed {required} role. Your current session is not authorized for this surface.</p>
        <Link to="/login">Return to sign in</Link>
      </section>
    </main>
  );
}
