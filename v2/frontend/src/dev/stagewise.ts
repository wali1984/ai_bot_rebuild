// DEV-ONLY: mounts the Stagewise visual-editing toolbar on the running Vite app.
//
// What it gives you: on localhost:5173 you get a small toolbar; click/select any
// element on the LIVE page, type a prompt, and Stagewise hands that element's
// context to your connected AI coding agent (Claude Code / Copilot / Cursor) to
// edit the actual React source. It is "visually edit the live website with AI"
// without adopting a new styling system.
//
// SAFETY:
//  - This is imported ONLY from a `import.meta.env.DEV` branch in main.tsx, which
//    Vite statically replaces with `false` in production builds, so this module
//    (and the `@stagewise/toolbar` devDependency) is dead-code-eliminated and
//    NEVER ships to production.
//  - It renders its own overlay UI; it does not touch app state, the real V2
//    payloads, or the live-gate. Any failure degrades silently — it must never
//    block or alter the app.
export async function mountStagewiseDevToolbar(): Promise<void> {
  try {
    const { initToolbar } = await import('@stagewise/toolbar');
    initToolbar({ plugins: [] });
  } catch (err) {
    // Dev convenience only — never let a missing/broken toolbar affect the app.
    // eslint-disable-next-line no-console
    console.warn('[stagewise] dev toolbar not mounted:', err);
  }
}
