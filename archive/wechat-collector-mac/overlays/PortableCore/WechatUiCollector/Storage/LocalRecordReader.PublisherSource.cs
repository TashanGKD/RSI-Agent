using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using WechatUiCollector.WechatDb;

namespace WechatUiCollector.Storage;
public sealed partial class LocalRecordReader
{
    internal const string PublisherRowKeysSql="SELECT rowid k FROM db_messages NOT INDEXED WHERE rowid>$after AND rowid<=$through ORDER BY rowid LIMIT $limit";
    internal const string PublisherChangeKeysSql="SELECT sequence k FROM record_changes INDEXED BY ix_record_changes_account WHERE account_key=$account AND sequence>$after AND sequence<=$through ORDER BY sequence LIMIT $limit";
    sealed record PublisherCursor(int Version,string Scope,
        long RowAfter,long? RowThrough,long ChangeAfter,long? ChangeThrough,long ObservedRowHigh,long ObservedChangeHigh);
    sealed class PublisherPageBudget(BoundedSourceLimits limits)
    {
        internal long Compressed,Decoded,Metadata,DecodedReserved;
        internal bool ReserveMetadata(long bytes) { if(bytes>limits.MaximumPageMetadataBytes-Metadata)return false;Metadata+=bytes;return true; }
        internal bool ReservePayload(long compressed,long decodedReservation) {
            if(compressed>limits.MaximumPageCompressedBytes-Compressed || decodedReservation>limits.MaximumPageDecodedBytes-DecodedReserved)return false;
            Compressed+=compressed;DecodedReserved+=decodedReservation;return true;
        }
    }
    static readonly string[] PublisherScalars={"account_key","conversation","sender_username","create_time","parse_status","message_type"};
    static readonly UTF8Encoding PublisherUtf8=new(false,true);
    internal async Task<BoundedSourcePage> ReadPublisherSourcePageAsync(string account,string? chat,string? cursor,PublisherSourceLane lane,PublisherSourceFilter filter,BoundedSourceLimits limits,CancellationToken token)
    {
        token.ThrowIfCancellationRequested();ValidatePublisherLimits(limits);
        if(lane is not (PublisherSourceLane.Rows or PublisherSourceLane.Changes) || filter is not (PublisherSourceFilter.AppMessages or PublisherSourceFilter.ArticleShares)) throw new ArgumentOutOfRangeException(nameof(lane));
        if(account is null || account.Length>8192 || (chat?.Length??0)>8192 || PublisherUtf8.GetByteCount(account)>8192 || (chat is not null && PublisherUtf8.GetByteCount(chat)>8192))throw new ArgumentException("publisher-source-scope-invalid");
        if(PublisherUtf8.GetByteCount(account)>limits.MaximumScalarBytes || (chat is not null && PublisherUtf8.GetByteCount(chat)>limits.MaximumScalarBytes))throw new ArgumentException("publisher-source-scope-exceeds-scalar-limit");
        if(SchemaVersion<26)throw new InvalidDataException("publisher-source-requires-schema26");
        var state=(await RowsAsync("SELECT CASE WHEN typeof(store_id)='text' AND length(CAST(store_id AS BLOB))<=1024 THEN store_id END store, floor_sequence floor, COALESCE((SELECT seq FROM sqlite_sequence WHERE name='record_changes'),0) high, COALESCE((SELECT MAX(rowid) FROM db_messages),0) rowhigh FROM record_change_state WHERE singleton=1",new(),token)).Single();
        if(state["store"] is not string instance)throw new InvalidDataException("publisher-source-store-invalid");
        string scope=Scope(new{instance,account,chat,filter});long floor=PublisherLong(state,"floor"),high=PublisherLong(state,"high"),rowHigh=PublisherLong(state,"rowhigh");
        PublisherCursor position;
        if(cursor is null)position=new(2,scope,0,rowHigh,high,null,rowHigh,high);
        else {
            if(cursor.Length>16384)throw new ArgumentException("publisher-source-cursor-invalid");
            try { position=JsonSerializer.Deserialize<PublisherCursor>(Convert.FromBase64String(cursor),new JsonSerializerOptions{MaxDepth=16})??throw new JsonException(); }
            catch(Exception e) when(e is JsonException or FormatException) { throw new ArgumentException("publisher-source-cursor-invalid"); }
            if(position.Version!=2 || position.Scope!=scope || position.RowAfter<0 || position.ChangeAfter<0 || position.ObservedRowHigh<position.RowAfter || position.ObservedChangeHigh<position.ChangeAfter || position.RowThrough<position.RowAfter || position.ChangeThrough<position.ChangeAfter)throw new ArgumentException("publisher-source-cursor-scope-invalid");
            if(position.ObservedRowHigh>rowHigh || position.ObservedChangeHigh>high || position.RowThrough>rowHigh || position.ChangeAfter>high || position.ChangeThrough>high)throw new PublisherSourceResetRequiredException();
            if(position.ChangeAfter<floor)throw new ChangeCursorExpiredException();
        }
        long through=lane==PublisherSourceLane.Rows ? position.RowThrough??rowHigh : position.ChangeThrough??high;
        long after=lane==PublisherSourceLane.Rows ? position.RowAfter : position.ChangeAfter;
        var parameters=new Dictionary<string,object?>{["$after"]=after,["$through"]=through,["$limit"]=limits.MaximumVisitedKeys};
        if(lane==PublisherSourceLane.Changes)parameters["$account"]=account;
        var keys=await RowsAsync(lane==PublisherSourceLane.Rows?PublisherRowKeysSql:PublisherChangeKeysSql,parameters,token);
        var budget=new PublisherPageBudget(limits);var records=new List<BoundedSourceRecord>();bool paused=false;
        foreach(var key in keys) {
            token.ThrowIfCancellationRequested();long k=PublisherLong(key,"k");
            long? row=k;RecordIdentity? identity=null;string operation="seed";
            if(lane==PublisherSourceLane.Changes) {
                var change=(await RowsAsync("SELECT CASE WHEN ($chat IS NULL OR conversation=$chat) THEN 1 ELSE 0 END eligible, typeof(conversation) chat_type,length(CAST(conversation AS BLOB)) chat_bytes,typeof(operation) op_type,length(CAST(operation AS BLOB)) op_bytes,CASE WHEN typeof(server_id)='integer' THEN server_id END sid FROM record_changes WHERE sequence=$key AND account_key=$account",new(){["$key"]=k,["$account"]=account,["$chat"]=chat},token)).SingleOrDefault();
                if(change is null)throw new PublisherSourceResetRequiredException();
                if(PublisherLong(change,"eligible")==0){after=k;continue;}
                long cb=PublisherLong(change,"chat_bytes"),ob=PublisherLong(change,"op_bytes");
                if((string?)change["chat_type"]!="text" || (string?)change["op_type"]!="text" || change["sid"] is not long || cb>limits.MaximumScalarBytes || ob>32) {
                    records.Add(new(null,null,BoundedSourceOutcome.Limit,"change-key-limit","unknown"));after=k;continue;
                }
                if(!budget.ReserveMetadata(128+cb+ob+PublisherUtf8.GetByteCount(account))){paused=true;break;}
                var value=(await RowsAsync("SELECT CASE WHEN typeof(conversation)='text' AND length(CAST(conversation AS BLOB))<=$scalar THEN CAST(conversation AS BLOB) END chat, CASE WHEN typeof(operation)='text' AND length(CAST(operation AS BLOB))<=32 THEN CAST(operation AS BLOB) END op FROM record_changes WHERE sequence=$key AND account_key=$account",new(){["$key"]=k,["$account"]=account,["$scalar"]=limits.MaximumScalarBytes},token)).Single();
                try { identity=new(account,PublisherText(value,"chat")!,PublisherLong(change,"sid").ToString(CultureInfo.InvariantCulture));operation=PublisherText(value,"op")!; }
                catch(DecoderFallbackException){records.Add(new(null,null,BoundedSourceOutcome.Invalid,"change-key-utf8","unknown"));after=k;continue;}
                if(operation is not ("insert" or "update" or "delete")){records.Add(new(identity,null,BoundedSourceOutcome.Unsupported,"change-operation", "unknown"));after=k;continue;}
                var located=await RowsAsync("SELECT rowid k FROM db_messages WHERE account_key=$account AND conversation=$chat AND server_id=$id",new(){["$account"]=account,["$chat"]=identity.Chat,["$id"]=PublisherLong(change,"sid")},token);
                row=located.Count==0?null:PublisherLong(located[0],"k");
                if(row is null){records.Add(new(identity,null,BoundedSourceOutcome.MissingRecord,"source-record-missing",operation));after=k;continue;}
            }
            var result=await PublisherRecordAsync(row!.Value,account,chat,filter,limits,budget,identity,operation,token);
            if(result.Paused){paused=true;break;}
            if(result.Record is not null)records.Add(result.Record);
            after=k;
        }
        bool completed=!paused && keys.Count<limits.MaximumVisitedKeys;if(completed)after=through;
        position=lane==PublisherSourceLane.Rows ? position with {RowAfter=after,RowThrough=completed?null:through,ObservedRowHigh=rowHigh,ObservedChangeHigh=high} : position with {ChangeAfter=after,ChangeThrough=completed?null:through,ObservedRowHigh=rowHigh,ObservedChangeHigh=high};
        token.ThrowIfCancellationRequested();
        return new(records,Encode(position),completed,keys.Count,lane==PublisherSourceLane.Rows?through:position.RowThrough??position.RowAfter,
            lane==PublisherSourceLane.Changes?through:position.ChangeThrough??position.ChangeAfter,budget.Compressed,budget.Decoded,budget.Metadata,paused);
    }
    async Task<(BoundedSourceRecord? Record,bool Paused)> PublisherRecordAsync(long row,string account,string? chat,PublisherSourceFilter filter,BoundedSourceLimits limits,PublisherPageBudget budget,RecordIdentity? changeIdentity,string operation,CancellationToken token)
    {
        var fields=new List<string>{"CASE WHEN typeof(server_id)='integer' THEN server_id END sid"};
        foreach(string column in PublisherScalars){fields.Add($"typeof({column}) {column}_type");fields.Add($"length(CAST({column} AS BLOB)) {column}_bytes");}
        fields.AddRange(new[]{"typeof(raw_z) raw_type","length(raw_z) raw_bytes","typeof(plain_content) plain_type","length(CAST(plain_content AS BLOB)) plain_bytes"});
        foreach(string column in new[]{"type_raw","appmsg_sub_type","sort_seq","real_sender_id","local_id","content_length","packed_info_length"})fields.Add($"CASE WHEN typeof({column})='integer' THEN {column} END {column}");
        var p=new Dictionary<string,object?>{["$row"]=row,["$account"]=account,["$chat"]=chat,["$shares"]=filter==PublisherSourceFilter.ArticleShares?1:0};
        var rows=await RowsAsync("SELECT "+string.Join(',',fields)+" FROM db_messages NOT INDEXED WHERE rowid=$row AND account_key=$account AND ($chat IS NULL OR conversation=$chat) AND message_type='AppMsg' AND ($shares=0 OR appmsg_sub_type=5)",p,token);
        if(rows.Count==0)return(changeIdentity is null?null:new(changeIdentity,null,BoundedSourceOutcome.Unsupported,"source-filtered",operation),false);
        var meta=rows[0];
        RecordIdentity? sourceIdentity=changeIdentity;
        BoundedSourceRecord Fail(BoundedSourceOutcome outcome,string code)=>new(sourceIdentity,null,outcome,code,operation);
        long metadata=256;
        foreach(string column in PublisherScalars) {
            string type=(string)meta[column+"_type"]!;long bytes=PublisherLong(meta,column+"_bytes");
            if(type!="text" && !(column=="sender_username" && type=="null"))return(Fail(BoundedSourceOutcome.Unsupported,"scalar-type"),false);
            if(bytes>limits.MaximumScalarBytes)return(Fail(BoundedSourceOutcome.Limit,"scalar-limit"),false);metadata+=bytes;
        }
        if(meta["sid"] is not long || new[]{"type_raw","appmsg_sub_type","sort_seq","real_sender_id","local_id","content_length","packed_info_length"}.Any(c=>meta[c] is not long))return(Fail(BoundedSourceOutcome.Unsupported,"numeric-type"),false);
        metadata+=128+PublisherLong(meta,"account_key_bytes")+PublisherLong(meta,"conversation_bytes");
        if(!budget.ReserveMetadata(metadata))return(null,true);
        // Preserve the original source key even when SQL refuses its payload.
        var identityRow=(await RowsAsync("SELECT CASE WHEN typeof(account_key)='text' AND length(CAST(account_key AS BLOB))<=$scalar THEN CAST(account_key AS BLOB) END a, CASE WHEN typeof(conversation)='text' AND length(CAST(conversation AS BLOB))<=$scalar THEN CAST(conversation AS BLOB) END c FROM db_messages NOT INDEXED WHERE rowid=$row",new(){["$row"]=row,["$scalar"]=limits.MaximumScalarBytes},token)).Single();
        try { sourceIdentity=new(PublisherText(identityRow,"a")!,PublisherText(identityRow,"c")!,PublisherLong(meta,"sid").ToString(CultureInfo.InvariantCulture)); }
        catch(DecoderFallbackException){return(Fail(BoundedSourceOutcome.Invalid,"key-utf8"),false);}
        long rawBytes=PublisherLong(meta,"raw_bytes"),plainBytes=PublisherLong(meta,"plain_bytes");string rawType=(string)meta["raw_type"]!,plainType=(string)meta["plain_type"]!;
        if(rawType is not ("blob" or "null") || plainType is not ("text" or "null"))return(Fail(BoundedSourceOutcome.Unsupported,"payload-type"),false);
        if(rawBytes>limits.MaximumCompressedBytes || plainBytes>limits.MaximumDecodedBytes)return(Fail(BoundedSourceOutcome.Limit,rawBytes>limits.MaximumCompressedBytes?"compressed-limit":"plain-limit"),false);
        // Reserve worst-case per-record decompression before reading its payload.
        // This includes plain bytes and bounds failed/corrupt attempts as well.
        long decodedReservation=rawType=="blob"?limits.MaximumDecodedBytes:plainBytes;
        if(!budget.ReservePayload(rawBytes,decodedReservation))return(null,true);
        var projection=new List<string>();foreach(string column in PublisherScalars)projection.Add($"CASE WHEN typeof({column})='text' AND length(CAST({column} AS BLOB))<=$scalar THEN CAST({column} AS BLOB) END {column}");
        projection.Add("CASE WHEN typeof(raw_z)='blob' AND length(raw_z)<=$compressed THEN raw_z END raw");
        projection.Add("CASE WHEN typeof(plain_content)='text' AND length(CAST(plain_content AS BLOB))<=$decoded THEN CAST(plain_content AS BLOB) END plain");
        var value=(await RowsAsync("SELECT "+string.Join(',',projection)+" FROM db_messages NOT INDEXED WHERE rowid=$row",new(){["$row"]=row,["$scalar"]=limits.MaximumScalarBytes,["$compressed"]=limits.MaximumCompressedBytes,["$decoded"]=limits.MaximumDecodedBytes},token)).Single();
        try {
            string a=PublisherText(value,"account_key")!,c=PublisherText(value,"conversation")!;
            var identity=new RecordIdentity(a,c,PublisherLong(meta,"sid").ToString(CultureInfo.InvariantCulture));
            string? plain=PublisherText(value,"plain");budget.Decoded+=plainBytes;
            var raw=rawType=="null"?new BoundedRawContent(BoundedRawOutcome.Missing,null,0,0):plainBytes==limits.MaximumDecodedBytes?new BoundedRawContent(BoundedRawOutcome.DecodedLimit,null,(int)rawBytes,0):RawContentCodec.DecompressBounded(value["raw"],limits.MaximumCompressedBytes,limits.MaximumDecodedBytes-(int)plainBytes,token);
            budget.Decoded+=raw.DecodedBytes;
            if(raw.Outcome is not (BoundedRawOutcome.Ready or BoundedRawOutcome.Missing))return(new(identity,null,raw.Outcome is BoundedRawOutcome.DecodedLimit or BoundedRawOutcome.CompressedLimit?BoundedSourceOutcome.Limit:BoundedSourceOutcome.Invalid,"raw-"+raw.Outcome.ToString(),operation),false);
            if(!DateTimeOffset.TryParse(PublisherText(value,"create_time"),CultureInfo.InvariantCulture,DateTimeStyles.None,out var time) || !Enum.TryParse<WechatDbMessageParseStatus>(PublisherText(value,"parse_status"),out var status) || !Enum.IsDefined(status))return(new(identity,null,BoundedSourceOutcome.Unsupported,"source-metadata-invalid",operation),false);
            var message=new WechatDbMessage(PublisherLong(meta,"sid"),0,WechatDbMessageType.AppMsg,PublisherLong(meta,"type_raw"),PublisherLong(meta,"appmsg_sub_type"),PublisherLong(meta,"sort_seq"),c,PublisherLong(meta,"real_sender_id"),PublisherText(value,"sender_username"),time,status,plain,raw.Text,PublisherLong(meta,"content_length"),PublisherLong(meta,"packed_info_length"),null){AccountKey=a,LocalId=PublisherLong(meta,"local_id")};
            return(new(identity,message,raw.Outcome==BoundedRawOutcome.Missing?BoundedSourceOutcome.MissingRaw:BoundedSourceOutcome.Ready,raw.Outcome==BoundedRawOutcome.Missing?"raw-missing":"ready",operation),false);
        }
        catch(DecoderFallbackException){return(Fail(BoundedSourceOutcome.Invalid,"scalar-utf8"),false);}
    }
    static long PublisherLong(IReadOnlyDictionary<string,object?> values,string key)=>values[key] is null?0:(long)values[key]!;
    static string? PublisherText(IReadOnlyDictionary<string,object?> values,string key)=>values[key] is byte[] bytes?PublisherUtf8.GetString(bytes):null;
    static void ValidatePublisherLimits(BoundedSourceLimits x)
    {
        ArgumentNullException.ThrowIfNull(x);
        if(x.MaximumVisitedKeys is <1 or >32 || x.MaximumCompressedBytes is <1 or >65536 || x.MaximumDecodedBytes is <1 or >262144 || x.MaximumScalarBytes is <1 or >8192 || x.MaximumPageCompressedBytes<x.MaximumCompressedBytes || x.MaximumPageCompressedBytes>2097152 || x.MaximumPageDecodedBytes<x.MaximumDecodedBytes || x.MaximumPageDecodedBytes>8388608 || x.MaximumPageMetadataBytes<512+10*x.MaximumScalarBytes || x.MaximumPageMetadataBytes>262144)throw new ArgumentOutOfRangeException(nameof(x));
    }
}
