import {useState} from 'react';
import {Icon, type IconName} from './icons';
import {applyTheme, storedTheme, type ThemeChoice} from './theme';

/** Light, dark, or follow the device. The choice is remembered in this browser. */
export default function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  const options: {key: ThemeChoice; label: string; icon: IconName}[] = [
    {key: 'auto', label: 'Match my device', icon: 'monitor'}, {key: 'light', label: 'Light mode', icon: 'sun'}, {key: 'dark', label: 'Dark mode', icon: 'moon'},
  ];
  return <div className="themeswitch" role="group" aria-label="Color theme">
    {options.map(o => <button key={o.key} aria-pressed={choice === o.key} aria-label={o.label} title={o.label}
      onClick={() => { applyTheme(o.key); setChoice(o.key); }}><Icon name={o.icon} size={15}/></button>)}
  </div>;
}
