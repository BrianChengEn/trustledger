import {readFileSync, readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, it} from 'vitest';
import {SRC, leakFacts, ownLabelGap, references, publicSources} from './facts';
import {model} from './data';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const text = (path: string) => readFileSync(resolve(root, path), 'utf8');

describe('documented facts really appear in their cited source files', () => {
  it('every cited source file exists and is not empty', () => {
    for (const path of Object.values(SRC)) expect(text(path).length).toBeGreaterThan(100);
  });
  it('the own-label leakage gaps are quoted exactly', () => {
    const notes = text(SRC.leakage);
    for (const value of Object.values(ownLabelGap)) expect(notes).toContain(value);
  });
  it('the leakage-audit counts are quoted exactly', () => {
    const notes = text(SRC.leakage);
    expect(notes).toContain(leakFacts.laterRowsSource);
    expect(notes).toContain('test 與凍結率的最大絕對差：' + leakFacts.testMaxDiff);
    expect(notes).toContain('test 未見過的 merchant id：' + leakFacts.unseenTestMerchants);
  });
  it('the published reference numbers are in the shortlist or findings', () => {
    const all = text(SRC.shortlist) + text(SRC.findings);
    for (const needle of ['precision 0.73，recall 0.81', 'precision 0.83，recall 0.61', '0.9578']) expect(all).toContain(needle);
    expect(references.length).toBe(3);
  });
  it('the public source links are the ones the research cites', () => {
    const findings = text(SRC.findings);
    for (const s of publicSources) expect(findings).toContain(s.url);
  });
  it('919 is the number of alerts the reproduced current rules raise on the test slice', () => {
    const rules = model('prod_rules');
    expect(rules.alerts).toBe(919); expect(rules.TP + rules.FP).toBe(919); expect(rules.score_unique_values).toBe(2);
  });

  it('the page copy never makes unsupported benchmark or production claims', () => {
    const dir = 'frontend/src/fraudlab';
    const files = readdirSync(resolve(root, dir)).filter(f => /\.(tsx|ts)$/.test(f) && !/\.test\.|\.d\.ts$/.test(f));
    expect(files.length).toBeGreaterThan(8);
    const banned = ['kaggle #1', 'state-of-the-art', 'outperform', 'best in class', 'world-class', 'production-ready', 'proves'];
    for (const f of files) {
      const body = text(`${dir}/${f}`).toLowerCase();
      for (const phrase of banned) expect(body, `${f} contains "${phrase}"`).not.toContain(phrase);
    }
  });
  it('states that the model is offline research and not the product’s alert engine', () => {
    const all = ['FraudLab.tsx', 'Overview.tsx', 'Arena.tsx'].map(f => text(`frontend/src/fraudlab/${f}`)).join(' ');
    expect(all).toContain('System B');
    expect(all).toContain('offline');
    expect(all).toContain('does not produce the product’s alerts');
  });
});
