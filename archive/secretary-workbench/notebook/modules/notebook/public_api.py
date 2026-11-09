"""Discovery for implemented tool capabilities; never advertises a running secretary."""
def capabilities():
 return {'version':'4.4','work':{'query':['start','end','person','organization','keyword','cursor','limit','snapshot'],'time':'business-date-inclusive','sameObjects':True},'timezone':'Asia/Shanghai','objects':{'kinds':['action','project','goal','memo'],'query':['kind','state','domain','assignee','counterparty','start','end','keyword','cursor','limit']},
  'operations':{'atomic':['object','schedule','note','presentation'],'idempotency':'requestId','changes':'commit-sequence','history':'as-of migration baseline onward','restore':'preview + explicit fields + expectedRevision'},
  'time':{'deadline':'explicit nullable date','plan':'dated occurrence','followup':'date/time/condition, no automatic schedule','timersEnabled':False},
  'presentations':{'versioned':True,'humanAckOnly':True,'legacyAck':'expected object revision guards omitted presentation identity'},
  'linkedRecordRevisions':True,'sourceLocators':{'metadataOnlyOnline':True,'rawSourcesLocalOnly':True},'secretaryExecution':False}
