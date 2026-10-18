import {afterEach, describe, expect, it, vi} from 'vitest';
import {money, request, UNAUTHORIZED_EVENT} from './api';
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
  it('tells the app when the session is lost, but not for a wrong passcode',async()=>{
    const events: string[] = [];
    const bus = new EventTarget();
    vi.stubGlobal('window', bus); // the unit tests run without a browser
    bus.addEventListener(UNAUTHORIZED_EVENT, () => events.push('lost'));
    const reply = (code: string) => new Response(JSON.stringify({error: {code, message: 'x', request_id: 'r'}}), {status: 401});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply('invalid_credentials')).mockResolvedValueOnce(reply('auth_required')));
    await expect(request('/auth/login', {method: 'POST', body: '{}'})).rejects.toThrow('invalid_credentials');
    expect(events).toEqual([]);
    await expect(request('/transactions')).rejects.toThrow('auth_required');
    expect(events).toEqual(['lost']);
  });
  it('supports empty successful deletes',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(null,{status:204})));
    await expect(request('/memories/id',{method:'DELETE'})).resolves.toBeUndefined();
  });
});
