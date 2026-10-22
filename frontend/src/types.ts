export type Target = {id?:number;name:string;kind:'ping'|'dns'|'http';address:string;enabled:boolean};
export type Config = {settings:{interval_seconds:number;timeout_seconds:number;ping_count:number;retention_days:number};targets:Target[]};
export type Measurement = {timestamp:string;success:number|null;latency_ms:number|null;jitter_ms:number|null;packet_loss:number|null;error:string|null};
export type TargetData = Target & {latest:Measurement|null;stats:{samples:number;availability:number|null;latency_ms:number|null;jitter_ms:number|null;packet_loss:number|null}};
export type Point = {target_id:number;timestamp:string;latency_ms:number|null;jitter_ms:number|null;packet_loss:number|null;availability:number|null};
export type Outage = {id:number;target_id:number;name:string;kind:string;started_at:string;recovered_at:string|null;end_reason:string|null};
export type Dashboard = {targets:TargetData[];history:Point[];outages:Outage[];generated_at:string;bucket_seconds:number};
export type Health = {status:string;collector_running:boolean;last_cycle:string|null;error:string|null;gateway:string|null;mode:string};
