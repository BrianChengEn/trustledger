import {afterEach, describe, expect, it, vi} from 'vitest';
import {money, request} from './api';

afterEach(()=>vi.unstubAllGlobals());
describe('safe API behavior',()=>{
  it('formats demo USD amounts',()=>expect(money(11.99)).toBe('$11.99'));
  it('does not expose upstream bodies or raw secrets in error messages',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private upstream data',{status:500})));
    await expect(request('/transactions')).rejects.toThrow('API returned 500');
  });
  it('supports empty successful deletes',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(null,{status:204})));
    await expect(request('/memories/id',{method:'DELETE'})).resolves.toBeUndefined();
  });
});
