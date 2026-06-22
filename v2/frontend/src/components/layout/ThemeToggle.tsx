import { useEffect, useState } from 'react';

type ThemeMode = 'midnight-neural' | 'polar-signal';

const STORAGE_KEY = 'nervyx_theme';
const OLD_STORAGE_KEY = `${'alpha'}forge_theme`;
const LEGACY_STORAGE_KEY = 'ai_bot_v2_theme';

function readInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'midnight-neural';
  const stored = window.localStorage.getItem(STORAGE_KEY)
    ?? window.localStorage.getItem(OLD_STORAGE_KEY)
    ?? window.localStorage.getItem(LEGACY_STORAGE_KEY);
  const theme: ThemeMode = stored === 'light' || stored === 'polar-signal'
    ? 'polar-signal'
    : 'midnight-neural';
  if (window.localStorage.getItem(STORAGE_KEY) !== theme) {
    window.localStorage.setItem(STORAGE_KEY, theme);
  }
  window.localStorage.removeItem(OLD_STORAGE_KEY);
  window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  document.documentElement.dataset.nervyxTheme = theme;
  document.documentElement.dataset.theme = theme === 'polar-signal' ? 'light' : 'dark';
  document.documentElement.style.colorScheme = theme === 'polar-signal' ? 'light' : 'dark';
  return theme;
}

export function ThemeToggle(): JSX.Element {
  const [theme, setTheme] = useState<ThemeMode>(readInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.nervyxTheme = theme;
    document.documentElement.dataset.theme = theme === 'polar-signal' ? 'light' : 'dark';
    document.documentElement.style.colorScheme = theme === 'polar-signal' ? 'light' : 'dark';
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      <button
        type="button"
        className={theme === 'midnight-neural' ? 'theme-toggle__button theme-toggle__button--active' : 'theme-toggle__button'}
        aria-pressed={theme === 'midnight-neural'}
        onClick={() => setTheme('midnight-neural')}
      >
        Midnight
      </button>
      <button
        type="button"
        className={theme === 'polar-signal' ? 'theme-toggle__button theme-toggle__button--active' : 'theme-toggle__button'}
        aria-pressed={theme === 'polar-signal'}
        onClick={() => setTheme('polar-signal')}
      >
        Polar
      </button>
    </div>
  );
}
