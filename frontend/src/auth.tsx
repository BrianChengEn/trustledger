import {createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode} from 'react';
import {ApiError, request, UNAUTHORIZED_EVENT, type Role, type Session} from './api';

const PREVIEW = 'trustledger.preview';
const SIGNED_OUT: Session = {authenticated: false, role: null, login_required: true, admin_available: false, demo_edit_enabled: false};

export interface Auth {
  session: Session; loading: boolean; unreachable: boolean;
  /** An admin looking at the user's screens. Only meaningful for the admin role. */
  previewing: boolean;
  login: (role: Role, passcode: string) => Promise<string | null>;
  logout: () => Promise<void>;
  startPreview: () => void; stopPreview: () => void;
}
const Ctx = createContext<Auth | null>(null);
export const useAuth = () => {
  const value = useContext(Ctx);
  if (!value) throw new Error('useAuth outside provider');
  return value;
};

const loginProblem = (e: unknown): string => {
  if (e instanceof ApiError) {
    if (e.code === 'invalid_credentials') return 'That passcode is not right. Check it and try again.';
    if (e.code === 'admin_not_configured') return 'Admin sign-in is not set up on this server. Set DEMO_ADMIN_PASSCODE in backend/.env and restart the backend.';
    if (e.code === 'too_many_attempts') return 'Too many attempts. Wait a minute, then try again.';
    return 'Sign-in failed. Please try again.';
  }
  return 'Cannot reach the TrustLedger server. Start the backend on port 8000, then try again.';
};

export function AuthProvider({children}: {children: ReactNode}) {
  const [session, setSession] = useState<Session>(SIGNED_OUT);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const [previewing, setPreviewing] = useState(() => {
    try { return window.sessionStorage.getItem(PREVIEW) === '1'; } catch { return false; }
  });
  const remember = (value: boolean) => {
    setPreviewing(value);
    try { if (value) window.sessionStorage.setItem(PREVIEW, '1'); else window.sessionStorage.removeItem(PREVIEW); } catch { /* not remembered */ }
  };

  useEffect(() => {
    let active = true;
    request<Session>('/auth/me', undefined, 8000)
      .then(view => { if (active) setSession(view); })
      .catch(() => { if (active) setUnreachable(true); })
      .finally(() => { if (active) setLoading(false); });
    const lost = () => { setSession(s => ({...s, authenticated: false, role: null})); remember(false); };
    window.addEventListener(UNAUTHORIZED_EVENT, lost);
    return () => { active = false; window.removeEventListener(UNAUTHORIZED_EVENT, lost); };
  }, []);

  const login = useCallback(async (role: Role, passcode: string) => {
    try {
      const view = await request<Session>('/auth/login', {method: 'POST', body: JSON.stringify({role, passcode})}, 8000);
      setUnreachable(false); remember(false); setSession(view);
      return null;
    } catch (e) { if (!(e instanceof ApiError)) setUnreachable(true); return loginProblem(e); }
  }, []);
  const logout = useCallback(async () => {
    try { await request<Session>('/auth/logout', {method: 'POST', body: '{}'}, 8000); } catch { /* the cookie also expires on its own */ }
    remember(false);
    window.location.hash = '#/today';
    setSession(s => ({...s, authenticated: false, role: null}));
  }, []);

  const value = useMemo<Auth>(() => ({
    session, loading, unreachable, previewing: previewing && session.role === 'admin', login, logout,
    startPreview: () => remember(true), stopPreview: () => remember(false),
  }), [session, loading, unreachable, previewing, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
