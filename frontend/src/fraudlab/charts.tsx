import {useId, useState, type KeyboardEvent, type ReactNode} from 'react';
import {prCurve, type ModelResult, type Outcome} from './data';

/** One dot per ranked alert. Filled = ground-truth fraud, hollow = not. Arrow keys move; the chosen alert is announced. */
export function DotMatrix({total, isFraud, columns, selected, onSelect, summary}: {
  total: number; isFraud: (rank: number) => boolean; columns: number; selected: number | null; onSelect: (rank: number) => void; summary: string;
}) {
  const rowsN = Math.ceil(total / columns), size = 13, gap = 3, pad = 2;
  const w = columns * (size + gap) - gap + pad * 2, h = rowsN * (size + gap) - gap + pad * 2;
  const move = (e: KeyboardEvent) => {
    const at = selected ?? 1;
    const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowDown' ? columns : e.key === 'ArrowUp' ? -columns : 0;
    if (!delta) return;
    e.preventDefault(); onSelect(Math.max(1, Math.min(total, at + delta)));
  };
  return <div className="fl-dots" tabIndex={0} role="application" aria-label={summary + ' Use the arrow keys to inspect each alert.'} onKeyDown={move}>
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-hidden="true" focusable="false">
      {Array.from({length: total}, (_, i) => {
        const rank = i + 1, cx = pad + (i % columns) * (size + gap) + size / 2, cy = pad + Math.floor(i / columns) * (size + gap) + size / 2;
        const fraud = isFraud(rank);
        return <circle key={rank} cx={cx} cy={cy} r={size / 2 - 1} className={(fraud ? 'tp' : 'fp') + (selected === rank ? ' sel' : '')}
          onClick={() => onSelect(rank)}/>;
      })}
    </svg>
  </div>;
}

export interface Series {name: string; model: ModelResult; tone: string}

/** Exact precision-recall curves from the saved ranking. `k` marks the chosen alert budget on every curve. */
export function PRChart({series, k, caption}: {series: Series[]; k?: number; caption: ReactNode}) {
  const id = useId();
  const W = 520, H = 330, L = 44, R = 12, T = 10, B = 34, pw = W - L - R, ph = H - T - B;
  const x = (r: number) => L + r * pw, y = (p: number) => T + (1 - p) * ph;
  const drawn = series.filter(s => s.model.curve_ok);
  return <figure className="fl-chart">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={id + 't ' + id + 'd'}>
      <title id={id + 't'}>Precision-recall curves</title>
      <desc id={id + 'd'}>{drawn.map(s => `${s.name}: average precision ${s.model.average_precision.toFixed(4)}`).join('. ')}.</desc>
      {[0, .25, .5, .75, 1].map(v => <g key={v}>
        <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid"/><text x={L - 6} y={y(v) + 4} textAnchor="end">{v.toFixed(2)}</text>
        <line y1={T} y2={T + ph} x1={x(v)} x2={x(v)} className="grid"/><text x={x(v)} y={H - 14} textAnchor="middle">{v.toFixed(2)}</text></g>)}
      <text x={L + pw / 2} y={H - 1} textAnchor="middle" className="axis">Recall (share of the 1,200 test fraud found)</text>
      <text transform={`translate(11 ${T + ph / 2}) rotate(-90)`} textAnchor="middle" className="axis">Precision</text>
      {drawn.map(s => {
        const pts = prCurve(s.model);
        const d = 'M' + x(0).toFixed(1) + ' ' + y(1).toFixed(1) + pts.map(p => ` L${x(p.recall).toFixed(1)} ${y(p.precision).toFixed(1)}`).join('');
        return <path key={s.name} d={d} className={'curve ' + s.tone} fill="none"/>;
      })}
      {k !== undefined && drawn.map(s => {
        const idx = s.model.fraud_ranks.filter(r => r <= k).length;
        if (!idx) return null;
        return <circle key={s.name} cx={x(idx / 1200)} cy={y(idx / k)} r={5} className={'mark ' + s.tone}/>;
      })}
    </svg>
    <figcaption>{caption}</figcaption>
    <details><summary>Show the data behind this chart</summary>
      <table className="fl-table"><thead><tr><th>Model</th><th>Average precision</th><th>Precision at the chosen budget</th></tr></thead>
        <tbody>{series.map(s => <tr key={s.name}><td>{s.name}</td><td>{s.model.average_precision.toFixed(6)}</td>
          <td>{k === undefined ? '' : (s.model.fraud_ranks.filter(r => r <= k).length / k).toFixed(4)}</td></tr>)}</tbody></table></details>
  </figure>;
}

/** Predicted alert / not alert against ground truth fraud / not fraud. The four cells are the only outcomes. */
export function ConfusionGrid({o}: {o: Outcome}) {
  const cell = (cls: string, tag: string, n: number, text: string) => <div className={'cell ' + cls}><b>{tag}</b><strong>{n.toLocaleString()}</strong><small>{text}</small></div>;
  return <div className="fl-confusion" role="table" aria-label={`Outcomes at ${o.k} alerts: ${o.tp} true positives, ${o.fp} false positives, ${o.fn} false negatives, ${o.tn} true negatives`}>
    <span className="corner"/><span className="colhead">Ground truth: fraud</span><span className="colhead">Ground truth: not fraud</span>
    <span className="rowhead">Model alert (top {o.k.toLocaleString()})</span>{cell('tp', 'TP', o.tp, 'alerted, was fraud')}{cell('fp', 'FP', o.fp, 'alerted, was not fraud')}
    <span className="rowhead">Not alerted</span>{cell('fn', 'FN', o.fn, 'fraud we missed')}{cell('tn', 'TN', o.tn, 'correctly left alone')}
  </div>;
}

export interface Bar {key: string; label: string; value: number | null; note?: string; tone: string; badge?: string}
/** Horizontal bars. A missing value is shown as "not reported", never as zero. */
export function Bars({items, max, format, selected, onSelect, label}: {
  items: Bar[]; max: number; format: (v: number) => string; selected?: string; onSelect?: (key: string) => void; label: string;
}) {
  return <ul className="fl-bars" aria-label={label}>{items.map(b => <li key={b.key} className={selected === b.key ? 'on' : ''}>
    <button type="button" onClick={() => onSelect?.(b.key)} aria-pressed={selected === b.key} disabled={!onSelect}>
      <span className="name">{b.label}{b.badge && <i className="badge">{b.badge}</i>}</span>
      <span className="track">{b.value === null ? <em>not reported</em> : <span className={'fill ' + b.tone} style={{width: `${Math.max(1, (b.value / max) * 100)}%`}}/>}</span>
      <span className="val">{b.value === null ? 'N/A' : format(b.value)}</span></button>
    {b.note && <small>{b.note}</small>}</li>)}</ul>;
}
