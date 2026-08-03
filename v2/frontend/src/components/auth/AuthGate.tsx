import '../../pages/login/authPages.css';

export function AuthGate({ message = 'Checking secure session' }: { message?: string }): JSX.Element {
  return (
    <main className="auth-state-page" data-testid="auth-gate">
      <section className="auth-state-card">
        <span className="auth-state-card__eyebrow">Secure access</span>
        <h1>{message}</h1>
        <p>Protected content is hidden until the backend confirms your session and role.</p>
      </section>
    </main>
  );
}
