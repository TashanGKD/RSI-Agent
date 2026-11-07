using System.Text;
using System.Text.Json;
using WechatUiCollector.Models;
using WechatUiCollector.Output;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    string timelineEstimate = "", timelinePath = "", timelineLastExport = "";
    readonly Dictionary<string,string> pendingTimelines = new();
    static TimelineQuery WholeTimeline() => new(DateTimeOffset.MinValue, DateTimeOffset.MaxValue, null, null, TimelineSource.All);
    async Task TimelineActionAsync(string action, JsonElement command, CancellationToken token)
    {
        if (action == "estimateTimeline")
        {
            timelineEstimate = $"预计导出 {await store.CountTimelineAsync(WholeTimeline(), token):N0} 条记录";
        }
        else if (action == "exportTimeline")
        {
            if (exportBusy) throw new ArgumentException("另一项导出正在进行，请等待完成。");
            if (pendingTimelines.Count >= 16) throw new ArgumentException("待选择的导出过多，请先完成或取消已有选择。");
            string id = "timeline-" + Guid.NewGuid().ToString("N"); pendingTimelines.Add(id,store.DatabasePath);
            Post("export",new{type="macNative",command="saveDocument",page="export",requestId=id,title="导出微信采集记录",filename=$"wechat-export-{DateTime.Now:yyyyMMdd-HHmm}.md"});
        }
        else
        {
            if (!pendingTimelines.Remove(Text(command,"requestId"),out var sourcePath)) throw new ArgumentException("时间线导出选择已过期，请重新发起。");
            string destination=Text(command,"path"); if(destination.Length==0)return;
            if(sourcePath!=store.DatabasePath)throw new ArgumentException("保存位置已改变，请重新发起时间线导出。");
            if(exportBusy)throw new ArgumentException("另一项导出正在进行，请重新发起。");
            exportBusy=true;exportCancellation?.Dispose();exportCancellation=OperationCancellation();var workToken=exportCancellation.Token;var sourceStore=store;
            timelineEstimate="正在导出时间线…";timelinePath="输出位置："+destination;
            exportWork=TrackShutdownTask(Task.Run(async()=>{
                string? temporary=null;
                try{
                    var path=SafeUserOutput(destination);
                    ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(path)!);
                    temporary=path+"."+Guid.NewGuid().ToString("N")+".tmp";
                    var entries=await sourceStore.QueryTimelineAsync(WholeTimeline(),workToken);
                    await ProtectedFileSystem.WriteAllTextAsync(temporary,TimelineFormatter.Format(entries,"markdown",includeStructuredMetadata:false),new UTF8Encoding(false),workToken);
                    workToken.ThrowIfCancellationRequested();ProtectedFileSystem.Move(temporary,path,overwrite:true);
                    timelineEstimate=$"实际导出 {entries.Count:N0} 条记录；{TimelineCompletenessReport.Build(entries).ToSummary()}";
                    timelineLastExport=$"最近导出：{DateTime.Now:MM-dd HH:mm} · {entries.Count:N0} 条";completedPath=path;exportStatus="时间线导出完成。";
                }
                catch(OperationCanceledException){timelineEstimate="导出已取消，已有文件保留。";exportStatus=timelineEstimate;}
                catch(Exception error)when(error is not OutOfMemoryException){timelineEstimate="时间线导出未完成，原文件保留。";exportStatus=timelineEstimate;}
                finally{
                    CleanupUserTemporary(temporary);
                    await gate.WaitAsync();try{exportBusy=false;Post("export",await ExportStateAsync(CancellationToken.None));}finally{gate.Release();}
                }
            }));
        }
        Post("export",await ExportStateAsync(token));
    }
}
