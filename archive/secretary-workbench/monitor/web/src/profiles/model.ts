import type {Evidence,Employee,Task} from '../model';
export type EntityKind='person'|'organization'|'project'|'channel'|'source'|'collaborator'|'workspace';
export type RelationType='serves'|'reads'|'communicates'|'delivers'|'focuses'|'collaborates'|'maintains';
export type Statement={text:string;evidence:Evidence[]};
export type Relation={id:string;label:string;kind:EntityKind;realId:string;types:RelationType[];scope:string;evidence:Evidence[]};
export type ProfileHistory={time:string;label:string;kind?:string;note?:string;evidence:Evidence[]};
export type EmployeeProfile={employee:string;schemaVersion?:number;roleName:string;purpose:string;identityEvidence:Evidence[];responsibilities:Statement[];relations:Relation[];boundaries:Statement[];routines:{label:string;schedule:string;recipient:string;evidence:Evidence[]}[];resources:{label:string;kind:string;note:string;evidence:Evidence[]}[];capabilities:{label:string;agreement:string;evidence:Evidence[]}[];lifecycle:{state:'active'|'paused'|'retired'|'transferred'|'unknown';note:string;evidence:Evidence[]};history:ProfileHistory[];observedHistory:ProfileHistory[];communicationIdentity?:{label:string;note:string;evidence:Evidence[]};automation?:{id:string;state:string;note:string;sourceId:string|null;fields?:Record<string,string>;evidence?:Evidence[]};observations?:{hourlyObservedClaim?:boolean;mentionEnabledClaim?:boolean;stage?:string;idleWakeVerifiedClaim?:boolean;busyRetentionVerifiedClaim?:boolean;hourlyDedupVerifiedClaim?:boolean;outboundVerifiedClaim?:boolean;scope?:string;fileChecks:{label:string;hashMatches:boolean;jsonReadable:boolean}[];note?:string;evidence:Evidence[]}|null;health:{lastSuccess?:string;lastAttempt?:string;error:string|null};sourceIds?:string[]};
export type HubMode='relations'|'people'|'capabilities'|'lifecycle';
export const RELATION_LABEL:Record<RelationType,string>={serves:'服务 / 负责结果',reads:'读取',communicates:'沟通',delivers:'交付',focuses:'重点关注',collaborates:'协作分工',maintains:'维护'};
export const KIND_LABEL:Record<EntityKind,string>={person:'人',organization:'组织',project:'项目',channel:'群聊 / 会话',source:'资料 / 文档',collaborator:'协作者',workspace:'工作资源'};
export const LIFECYCLE_LABEL:Record<EmployeeProfile['lifecycle']['state'],string>={active:'持续服务（记录）',paused:'岗位暂停（记录）',retired:'已停用（记录）',transferred:'已移交（记录）',unknown:'岗位状态未单列'};
export type Band='services'|'channels'|'sources'|'collaboration';
export function bandOf(r:Relation):Band{if(r.types.includes('serves'))return 'services';if(r.kind==='channel')return 'channels';if(r.kind==='collaborator'||r.types.includes('collaborates'))return 'collaboration';if(r.types.includes('reads'))return 'sources';return 'collaboration'}
export const accountIsNotEmployee=(r:Relation)=>r.label==='吾愿'&&!r.types.includes('serves');
export const selectedEmployees=(employees:Employee[],person:string)=>employees.filter(e=>person==='all'||e.id===person);
export function relationsFor(profile:EmployeeProfile|undefined,band:Band){return [...(profile?.relations.filter(r=>bandOf(r)===band)??[])].sort((a,b)=>(Number(b.types.includes('delivers'))*4+Number(b.types.includes('communicates'))*2+Number(b.types.includes('focuses')))-(Number(a.types.includes('delivers'))*4+Number(a.types.includes('communicates'))*2+Number(a.types.includes('focuses'))))}
export function currentWork(tasks:Task[],employee:string){return tasks.filter(t=>t.employee===employee&&t.kind!=='history')}
export function isProfileMode(value:string):value is HubMode{return ['relations','people','capabilities','lifecycle'].includes(value)}
