using System.Text.Json;
using WechatUiCollector.Storage;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.WechatDb;
using WechatUiCollector.Cli;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    string exportAccount = "", exportSearch = "", exportCategory = "all", completedPath = "", exportStatus = "", exportTaskState = "idle";
    HashSet<string> selectedExports = [];
    bool allExports, exportBusy, exportReading;
    IReadOnlyList<WechatDbConversation> exportConversations = [];
    readonly Dictionary<string, (LocalChatExportQuery Query, string Format, string Database)> pendingExports = new();
    CancellationTokenSource? exportCancellation;
    IProgress<long> CreateExportProgress(CancellationTokenSource cancellation) => new InlineProgress<long>(count =>
    {
        if (ReferenceEquals(exportCancellation, cancellation) && exportBusy && exportTaskState == "running" && !cancellation.IsCancellationRequested && !LifetimeToken.IsCancellationRequested)
            exportStatus = $"已写入 {count:N0} 条…";
    });
    async Task ExportAsync(string action, JsonElement command, CancellationToken token)
    {
        if (exportAccount.Length == 0) exportAccount = (await store.ListDbAccountsAsync(token)).FirstOrDefault() ?? "";
        switch (action)
        {
            case "ready": case "refreshAccounts": break;
            case "pageRendered": return;
            case "estimateTimeline": case "exportTimeline": case "saveDocument": await TimelineActionAsync(action,command,token); return;
            case "selectAccount":
                var key = Text(command, "key"); if (!(await store.ListDbAccountsAsync(token)).Contains(key)) throw new ArgumentException("账号不存在。");
                exportAccount = key; selectedExports.Clear(); allExports = false; break;
            case "search": exportSearch = Text(command, "value"); exportCategory = Text(command, "category"); break;
            case "toggleConversation":
                string username = Text(command, "username");
                if (!exportConversations.Any(c => c.Username == username)) throw new ArgumentException("会话不存在。");
                if (!selectedExports.Remove(username)) selectedExports.Add(username); break;
            case "setAllConversations": allExports = command.TryGetProperty("value", out var checkedValue) && checkedValue.ValueKind == JsonValueKind.True; break;
            case "clearSelection": selectedExports.Clear(); allExports = false; break;
            case "count": exportStatus = $"当前范围 {await store.CountLocalExportAsync(ExportQuery(command), token):N0} 条；导出时以实际快照为准。"; break;
            case "exportChats":
                if (exportBusy) throw new ArgumentException("另一项导出正在进行，请等待完成。");
                var query = ExportQuery(command); var format = Text(command, "format");
                if (!new[] { "jsonl", "json", "markdown" }.Contains(format)) throw new ArgumentException("未知导出格式。");
                if(pendingExports.Count>=16)throw new ArgumentException("待选择的导出过多，请完成或取消已有选择。");
                string requestId = Guid.NewGuid().ToString("N"); pendingExports[requestId] = (query, format, store.DatabasePath);
                Post("export", new { type = "macNative", command = "saveExport", page = "export", requestId, filename = "微信聊天记录." + (format == "markdown" ? "md" : format) }); break;
            case "saveExport":
                if (!pendingExports.Remove(Text(command, "requestId"), out var pending)) throw new ArgumentException("导出选择已过期，请重试。");
                var path = Text(command, "path");
                if (path.Length == 0)
                {
                    if (!exportBusy) { completedPath = ""; exportStatus = "未选择输出位置"; exportTaskState = "cancelled"; }
                    break;
                }
                if(exportBusy)throw new ArgumentException("另一项导出正在进行，请等待完成后重新发起。");
                if(pending.Database!=store.DatabasePath)throw new ArgumentException("记录保存位置已改变，请重新发起导出。");
                exportBusy = true; exportCancellation?.Dispose(); var cancellation = exportCancellation = OperationCancellation(); var workToken = cancellation.Token; var exportStore = store;
                exportStatus = "正在导出…"; exportTaskState = "running";
                exportWork = TrackShutdownTask(Task.Run(async () =>
                {
                    try
                    {
                        path=SafeUserOutput(path);
                        var count = await exportStore.ExportLocalChatsAsync(pending.Query, path, pending.Format, CreateExportProgress(cancellation), workToken);
                        completedPath = path; exportStatus = $"导出完成，共 {count:N0} 条。"; exportTaskState = "complete";
                    }
                    catch (OperationCanceledException) { exportStatus = "导出已取消。"; exportTaskState = "cancelled"; }
                    catch (Exception error) when(error is not OutOfMemoryException) { exportStatus = "导出未完成，原文件已保留。"; exportTaskState = "failed"; RuntimeEventSource.Emit(AppLogLevel.Error,"MAC_CHAT_EXPORT_FAILED","MacExport","聊天导出未完成。",new Dictionary<string,object?>{["errorType"]=error.GetType().Name}); }
                    finally { await gate.WaitAsync(); try { exportBusy = false; Post("export", await ExportStateAsync(CancellationToken.None)); } finally { gate.Release(); } }
                })); break;
            case "cancelExport": case "cancelOperation": exportCancellation?.Cancel(); break;
            case "cancelRead": return;
            case "openExportFolder": if (completedPath.Length > 0) Post("export", new { type = "macNative", command = "reveal", path = completedPath }); break;
            default: throw new NotSupportedException("此功能的 Mac 适配尚未完成，未执行操作。");
        }
        if (action is "ready" or "refreshAccounts" or "selectAccount" or "search")
        {
            exportReading = true; Post("export", await ExportStateAsync(token));
            try { exportConversations = await store.ListDbConversationsAsync(exportAccount, exportSearch, 0, token, string.IsNullOrEmpty(exportCategory) ? "all" : exportCategory, 10000); }
            finally { exportReading = false; }
        }
        Post("export", await ExportStateAsync(token));
    }
    LocalChatExportQuery ExportQuery(JsonElement command)
    {
        if (exportAccount.Length == 0 || !allExports && selectedExports.Count == 0) throw new ArgumentException("请先选择账号与导出会话。");
        var range = WechatDbDateFilter.Resolve(ParseDate(Text(command, "from")), ParseDate(Text(command, "to")));
        return new LocalChatExportQuery(exportAccount, allExports ? [] : selectedExports.ToArray(), range.From, range.ToExclusive);
    }
    async Task<object> ExportStateAsync(CancellationToken token)
    {
        var accounts = await store.ListDbAccountsAsync(token);
        return new { type = "state", accounts = accounts.Select(key => new { key, label = "微信账号" }), account = exportAccount, accountLabel = "微信账号",
            conversations = exportConversations.Select(c => new { username = c.Username, displayName = c.DisplayName, avatar = AvatarUrl(exportAccount, c.AvatarHash), preview = c.Preview ?? "", time = c.LocalLatest.ToString("MM-dd"), category = c.CategoryLabel, isChecked = allExports || selectedExports.Contains(c.Username) }),
            selectedCount = selectedExports.Count, selectedIds = selectedExports.ToArray(), loaded = true, taskState = exportTaskState, taskStatus = exportStatus, completedPath,
            allConversations = allExports, lastUpdated = "", scopeSummary = allExports ? "将导出当前账号全部会话。" : selectedExports.Count == 0 ? "先勾选要导出的会话。" : $"将导出 {selectedExports.Count} 个已选会话。", formatHint = "", status = feedback.Length > 0 ? feedback : exportStatus,
            busy = exportBusy, reading = exportReading, legacyVisible = true, estimate = timelineEstimate, exportPath = timelinePath, lastExport = timelineLastExport, backfillRunning = false, backfillPaused = false, backfillStatus = "", backfillQueue = Array.Empty<object>(), collectorRunning = false };
    }
}
