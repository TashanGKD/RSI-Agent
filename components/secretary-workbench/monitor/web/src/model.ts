import type {ModelAccounts} from './accounts/model';
import type {EmployeeProfile} from './profiles/model';
import type {WorkOverview} from './work/model';
export type Evidence={id:string;quote:string};
export type Event={time:string;event:string;source_id:string};
export type Task={id:string;employee:string;title:string;state:string;pending:string;next:string;goal:string;origin:string;thought:string;time:string;confidence:string;evidence:Evidence[];trajectory:Event[];kind:string;who_owes?:string};
export type Source={id:string;label:string;path:string;line?:number;time:string;role:string;text:string};
export type Employee={id:string;threadId:string;name:string;role:string;notebook:string;runtime:string;current:string;queueCount:number|null;lastActivity:string;gap:string;turnHours:number;coverage:{messages:number;files:number;notes:number;first:string;last:string;reviewed:boolean}};
export type Snapshot={workOverview?:WorkOverview;modelAccounts?:ModelAccounts;profiles?:Record<string,EmployeeProfile>;generatedAt:string;historyCutoff:string;runtimeAt:string;employees:Employee[];tasks:Task[];warnings:string[];live?:{revision:string;intervalSeconds:number;cycles:number;lastCycleFinished:string;health:Record<string,{lastSuccess:string|null;lastAttempt:string|null;lastCutoff:string|null;error:string|null;runtimeError:string|null;runtimeAt:string}>}};
