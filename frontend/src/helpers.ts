import type { Point, TargetData } from './types';
export function fillGaps(points:Point[], bucketSeconds:number) {
  const result:Point[]=[];
  for (const point of points) {
    const previous=result.at(-1);
    if(previous){
      for(let ts=Date.parse(previous.timestamp)+bucketSeconds*1000;ts<Date.parse(point.timestamp);ts+=bucketSeconds*1000){
        result.push({target_id:point.target_id,timestamp:new Date(ts).toISOString(),latency_ms:null,jitter_ms:null,packet_loss:null,availability:null});
      }
    }
    result.push(point);
  }
  return result;
}
export function format(value:number|null|undefined, unit='ms') {return value == null ? '—' : `${value.toLocaleString('pt-BR',{maximumFractionDigits:1})} ${unit}`;}
export function connectionState(target:TargetData, interval:number, count:number, timeout:number, now=Date.now()) {
  if (!target.enabled) return 'Pausado';
  if (!target.latest) return 'Aguardando';
  if (now-Date.parse(target.latest.timestamp)>Math.max(interval*3,count*(timeout+1.5)*8)*1000) return 'Desatualizado';
  if (target.latest.success===null) return 'Erro de coleta';
  return target.latest.success ? 'Online' : 'Indisponível';
}
export function duration(start:string,end:string|null) {const seconds=Math.max(0,Math.floor(((end?Date.parse(end):Date.now())-Date.parse(start))/1000));return seconds<60?`${seconds}s`:seconds<3600?`${Math.floor(seconds/60)}min ${seconds%60}s`:`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}min`;}
