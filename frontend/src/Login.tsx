import {useState, type FormEvent} from 'react';
import {useAuth} from './auth';
import {Icon} from './icons';
import ThemeSwitch from './ThemeSwitch';
import {Seg} from './ui';
import type {Role} from './api';

/** The page before everything else. It is a demo gate for a localhost demo, not production authentication. */
export default function Login() {
  const {session, unreachable, login} = useAuth();
  const [role, setRole] = useState<Role>('user');
  const [passcode, setPasscode] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const adminOff = role === 'admin' && !session.admin_available && !unreachable;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setProblem('');
    const failure = await login(role, passcode);
    if (failure) { setProblem(failure); setPasscode(''); }
    setBusy(false);
  }

  return <div className="app"><div className="frame loginframe">
    <header className="topbar loginbar">
      <span className="logo"><span className="logomark"><Icon name="shieldCheck" size={20} weight={1.4}/></span>
        <span>TrustLedger<small>Synthetic demo</small></span></span>
      <ThemeSwitch/>
    </header>
    <main className="loginmain">
      <section className="loginintro" aria-label="About TrustLedger">
        <div className="eyebrow">Welcome</div>
        <h1>Your money, checked by rules, decided by you.</h1>
        <ul>
          <li><span className="icontile small"><Icon name="listChecks" size={15}/></span><span><b>Rules find unusual charges.</b> Nothing happens until you decide.</span></li>
          <li><span className="icontile small"><Icon name="lock" size={15}/></span><span><b>AI sees only a generalized summary.</b> Never a merchant name, an exact amount or an ID.</span></li>
          <li><span className="icontile small"><Icon name="hardDrive" size={15}/></span><span><b>Memory is opt-in</b> and you can delete it any time.</span></li>
        </ul>
      </section>
      <form className="loginform panel" onSubmit={submit} aria-labelledby="login-title">
        <h2 id="login-title"><Icon name="lock" size={18}/>Sign in</h2>
        <Seg label="Sign in as" value={role} onChange={next => { setRole(next); setProblem(''); setPasscode(''); }}
          options={[{key: 'user', label: 'User'}, {key: 'admin', label: 'Admin'}]}/>
        <p className="quiet">{role === 'user'
          ? 'Review your own charges, decide what is normal, and control what is remembered.'
          : 'Review the demo workspace and access the Nessie sandbox console.'}</p>
        <label htmlFor="passcode">Passcode</label>
        <input id="passcode" type="password" autoComplete="off" value={passcode} disabled={busy || adminOff}
          onChange={event => setPasscode(event.target.value)} aria-invalid={!!problem} aria-describedby={problem ? 'login-problem' : undefined}/>
        {adminOff && <p className="loginproblem" role="status">Admin sign-in is not set up on this server. Set DEMO_ADMIN_PASSCODE in backend/.env and restart the backend.</p>}
        {unreachable && !problem && <p className="loginproblem" role="alert">Cannot reach the TrustLedger server. Start the backend on port 8000, then reload.</p>}
        {problem && <p id="login-problem" className="loginproblem" role="alert">{problem}</p>}
        <button className="primary" type="submit" disabled={busy || adminOff}>{busy ? 'Signing in…' : 'Sign in'}<Icon name="arrowRight" size={16}/></button>
        <p className="quiet loginnote">Local synthetic demo only. User and Admin passcodes are blank by default; leave this field empty unless configured.</p>
      </form>
    </main>
    <footer className="foot">Synthetic data only · no real accounts · rules decide, you confirm · AI-assisted code, credited in the submission.</footer>
  </div></div>;
}
