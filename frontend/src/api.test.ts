import {afterEach, describe, expect, it, vi} from 'vitest';
import {money, request} from './api';
import {explanationModeCopy} from './lib';

afterEach(()=>vi.unstubAllGlobals());
describe('safe API behavior',()=>{
  it('formats demo USD amounts',()=>expect(money(11.99)).toBe('$11.99'));
  it('does not expose upstream bodies or raw secrets in error messages',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private upstream data',{status:500})));
    await expect(request('/transactions')).rejects.toThrow('API returned 500');
  });
  it('does not call template or fallback text a live Gemini explanation',()=>{
    expect(explanationModeCopy('template', false).title).toBe('Rules explanation');
    expect(explanationModeCopy('fallback', false).detail).toContain('not from Gemini');
    expect(explanationModeCopy('gemini-live', false).title).toBe('Live Gemini explanation');
    expect(explanationModeCopy('gemini-live', true).title).toBe('Gemini explanation reused');
    expect(explanationModeCopy('template', false).detail).not.toContain('Live Gemini');
  });
  it('supports empty successful deletes',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(null,{status:204})));
    await expect(request('/memories/id',{method:'DELETE'})).resolves.toBeUndefined();
  });
});
