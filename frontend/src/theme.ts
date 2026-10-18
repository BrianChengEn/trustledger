export type ThemeChoice = 'auto' | 'light' | 'dark';
const KEY = 'trustledger.theme';

export function storedTheme(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    if (value === 'light' || value === 'dark') return value;
  } catch { /* storage unavailable: follow the device */ }
  return 'auto';
}

/** "auto" follows the device or browser setting; light and dark are the user's explicit choice, remembered here. */
export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === 'auto') root.removeAttribute('data-theme'); else root.dataset.theme = choice;
  try {
    if (choice === 'auto') window.localStorage.removeItem(KEY); else window.localStorage.setItem(KEY, choice);
  } catch { /* the choice just will not persist */ }
}
applyTheme(storedTheme());
