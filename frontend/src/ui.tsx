import type {CSSProperties, ReactNode} from 'react';
import {Icon, type IconName} from './icons';
import type {Tone} from './lib';

export const Chip = ({tone = 'neutral', icon, children}: {tone?: Tone | 'danger'; icon?: IconName; children: ReactNode}) =>
  <span className={'chip tone-' + tone}>{icon && <Icon name={icon} size={13}/>}{children}</span>;

export function Callout({tone = 'neutral', icon, title, children, role}: {
  tone?: Tone | 'danger'; icon: IconName; title: string; children?: ReactNode; role?: 'status' | 'alert'}) {
  return <div className={'callout tone-' + tone} role={role}>
    <Icon name={icon} size={18}/><div><strong>{title}</strong>{children && <p>{children}</p>}</div></div>;
}

export function PageHead({eyebrow, title, children, actions}: {eyebrow: string; title: string; children?: ReactNode; actions?: ReactNode}) {
  return <header className="pagehead">
    <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{children && <p>{children}</p>}</div>
    {actions && <div className="headactions">{actions}</div>}
  </header>;
}

export const stagger = (i: number) => ({'--i': i}) as CSSProperties;

export function Seg<T extends string>({label, value, options, onChange}: {
  label: string; value: T; options: {key: T; label: string; count?: number}[]; onChange: (v: T) => void}) {
  const index = Math.max(0, options.findIndex(o => o.key === value));
  // The highlight slides to the chosen option (see .seg::before).
  return <div className="seg" role="group" aria-label={label} style={{'--n': options.length, '--i': index} as CSSProperties}>
    {options.map(o => <button key={o.key} aria-pressed={value === o.key} onClick={() => onChange(o.key)}>
      {o.label}{o.count !== undefined && <span>{o.count}</span>}</button>)}
  </div>;
}
