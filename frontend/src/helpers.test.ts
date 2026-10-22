import { describe,it,expect } from 'vitest';
import { connectionState,format,duration,fillGaps } from './helpers';
import type { TargetData } from './types';
const now=Date.parse('2026-01-01T00:05:00Z');
const target:TargetData={id:1,name:'Local',kind:'ping',address:'127.0.0.1',enabled:true,stats:{samples:0,availability:null,latency_ms:null,jitter_ms:null,packet_loss:null},latest:null};
describe('Apresentação honesta das medições',()=>{
  it('não inventa valor quando faltam dados',()=>{expect(format(null)).toBe('—');expect(format(0)).toBe('0 ms');expect(connectionState(target,30,3,2,now)).toBe('Aguardando');});
  it('distingue falha, coleta, pausa e dados antigos',()=>{
    const latest={timestamp:'2026-01-01T00:05:00Z',success:1,latency_ms:10,jitter_ms:null,packet_loss:0,error:null};
    expect(connectionState({...target,latest},30,3,2,now)).toBe('Online');
    expect(connectionState({...target,latest:{...latest,success:0}},30,3,2,now)).toBe('Indisponível');
    expect(connectionState({...target,latest:{...latest,success:null}},30,3,2,now)).toBe('Erro de coleta');
    expect(connectionState({...target,latest},30,3,2,now+600000)).toBe('Desatualizado');
    expect(connectionState({...target,enabled:false,latest},30,3,2,now)).toBe('Pausado');
  });
  it('calcula a duração observada',()=>{expect(duration('2026-01-01T00:00:00Z','2026-01-01T00:01:03Z')).toBe('1min 3s');});
  it('insere lacunas reais entre períodos sem coleta',()=>{
    const p={target_id:1,timestamp:'2026-01-01T00:00:00Z',latency_ms:10,jitter_ms:2,packet_loss:0,availability:100};
    const filled=fillGaps([p,{...p,timestamp:'2026-01-01T00:03:00Z'}],60);
    expect(filled).toHaveLength(4);expect(filled[1].latency_ms).toBeNull();expect(filled[2].packet_loss).toBeNull();
  });
});
