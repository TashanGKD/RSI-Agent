using System.Diagnostics;
using System.Text.Json;
using WechatUiCollector.Cli;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    Task syncWork = Task.CompletedTask;
    CancellationTokenSource? syncCancellation;
    string syncStatus = "", syncDetail = "", syncOutcome = "notice", lastUpdated = "";
    int autoMinutes;
    bool autoPaused;
    CancellationTokenSource? autoCancellation;
    async Task SyncActionAsync(string action, JsonElement command, CancellationToken token)
    {
        if (action == "cancelSync") { syncCancellation?.Cancel(); autoPaused = autoMinutes > 0; return; }
        if (action == "auto")
        {
            int minutes = Number(command, "minutes", Number(command, "value", 0));
            if (!new[] { 0, 5, 10, 15, 30 }.Contains(minutes)) throw new ArgumentException("更新间隔无效。");
            SaveOptions(Options with { LocalChatAutoUpdateMinutes = minutes }); ConfigureAutoUpdate(minutes); return;
        }
        if (action == "repairSaved") StartSavedRepair(command);
        else if (action is "sync" or "reparse") StartSync(action == "reparse");
        Post("chat", await ChatStateAsync(token));
    }
    void ConfigureAutoUpdate(int minutes)
    {
        autoCancellation?.Cancel(); autoCancellation?.Dispose(); autoCancellation = OperationCancellation(); autoMinutes = minutes; autoPaused = false;
        if (minutes == 0) return;
        var token = autoCancellation.Token;
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            try { while (!token.IsCancellationRequested) { await Task.Delay(TimeSpan.FromMinutes(minutes), token); await gate.WaitAsync(token); try { if (!autoPaused && account.Length > 0 && syncWork.IsCompleted) StartSync(); } finally { gate.Release(); } } }
            catch (OperationCanceledException) { }
        }, token));
    }
    void StartSync(bool full = false)
    {
        if (ConnectionImportBlocked) { syncStatus = ConnectionRecoveryMessage; syncOutcome = "failed"; return; }
        if (!syncWork.IsCompleted || exportBusy || !voiceWork.IsCompleted || voiceQueue.Count > 0) { syncStatus = "另一项处理正在进行，请稍后更新。"; return; }
        if (account.Length == 0) { syncStatus = "请先选择账号。"; return; }
        var activeStore = store; string selected = account; syncCancellation?.Dispose(); syncCancellation = OperationCancellation(); var token = syncCancellation.Token;
        var configuredSource = Options.AttachmentSourceDirectory;
        syncStatus = full ? "正在准备全面重新解析…" : "正在准备本地读取…"; syncOutcome = "notice";
        syncWork = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                token.ThrowIfCancellationRequested();
                using var localImports = new MacImportProvider(directory, archive);
                var sourceBase = string.IsNullOrWhiteSpace(configuredSource)
                    ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
                    : WechatUiCollector.Configuration.ConfigurationLoader.ResolvePath(configuredSource, directory);
                var selectedSource = Path.GetFileName(Path.TrimEndingDirectorySeparator(sourceBase)) == selected ? sourceBase : Path.Combine(sourceBase, selected);
                var sourceRoot = localImports.ResolveAccountRoot(selectedSource);
                var progress = new InlineProgress<string>(text => { if (!token.IsCancellationRequested) { syncDetail = text; Post("chat", new { type = "state", syncing = true, syncStatus, syncDetail }); } });
                var result = await new WechatMessageImportService(activeStore, localImportProvider: localImports).ImportAsync(sourceRoot, progress: progress, cancellationToken: token, full: full);
                if (!result.Success) throw new IOException(result.Error);
                await gate.WaitAsync(token); try { archive = localImports.ArchiveDirectory; } finally { gate.Release(); }
                syncOutcome = "succeeded"; syncStatus = full ? "当前账号可验证的本地消息已全面重新解析。" : "当前账号的本地记录已更新。"; lastUpdated = $"最近更新 {DateTime.Now:MM-dd HH:mm}";
                await RefreshAfterRecordWorkAsync(activeStore, selected, token);
            }
            catch (OperationCanceledException) { syncOutcome = "cancelled"; syncStatus = "更新已取消，已提交批次和备份保留，可重试。"; }
            catch (Exception error) when (error is not OutOfMemoryException) { syncOutcome = "failed"; syncStatus = full ? "全面重新解析未完成，已保存记录与备份保留，请检查来源后重试。" : error is ArgumentException ? error.Message : "本地更新未完成，请检查微信登录和读取范围后重试。"; }
            finally { Post("chat", new { type = "state", syncing = false, syncOutcome, syncStatus, syncDetail, lastUpdated }); }
        }));
    }
    async Task RefreshAfterRecordWorkAsync(SqliteMessageStore activeStore, string selected, CancellationToken token)
    {
        await gate.WaitAsync(token);
        try
        {
            if (!ReferenceEquals(store, activeStore)) return;
            if (account == selected)
            {
                conversations = await activeStore.ListDbConversationsAsync(account, search, 0, token, category, conversationLimit);
                if (chat.Length > 0 && followingLatest) { var range = DateRange(); messages = (await activeStore.QueryDbMessagesAsync(account, chat, 100, range.From, range.ToExclusive, null, token)).Reverse().ToArray(); hasNewMessages = false; version++; }
                else if (chat.Length > 0) await CheckNewMessagesAsync(token);
            }
            EnsureKnowledgeIndex(); Post("chat", await ChatStateAsync(token));
        }
        finally { gate.Release(); }
    }
    void StartSavedRepair(JsonElement command)
    {
        if (!syncWork.IsCompleted || exportBusy || !voiceWork.IsCompleted || voiceQueue.Count > 0) { syncStatus = "另一项处理正在进行，请稍后修复。"; return; }
        if (account.Length == 0 || chat.Length == 0) throw new ArgumentException("请先选择要修复的会话。");
        WechatDbMessageParseStatus? status = null;
        var requested = Text(command, "status");
        if (requested.Length > 0)
        {
            if (!Enum.TryParse<WechatDbMessageParseStatus>(requested, out var parsed) || !Enum.IsDefined(parsed)) throw new ArgumentException("解析状态无效。");
            status = parsed;
        }
        var range = DateRange();
        var selected = account; var activeStore = store;
        var scope = new MessageRepairScope(selected, chat, range.From, range.ToExclusive, status);
        syncCancellation?.Dispose(); var cancellation = syncCancellation = OperationCancellation(); var token = cancellation.Token;
        syncStatus = "正在修复当前范围…"; syncOutcome = "notice";
        syncWork = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                var progress = new InlineProgress<string>(text => { if (!token.IsCancellationRequested) { syncDetail = text; Post("chat", new { type = "state", syncing = true, syncStatus, syncDetail }); } });
                var result = await activeStore.RepairSavedMessagesAsync(scope, progress, token);
                syncOutcome = "succeeded"; syncStatus = $"修复完成 · 更新 {result.Updated:N0} 条";
                syncDetail = $"检查 {result.Checked:N0} 条，缺少正文 {result.MissingRaw:N0} 条，仍未完整解析 {result.StillIncomplete:N0} 条。缺少正文请使用全面重新解析补源。";
                await RefreshAfterRecordWorkAsync(activeStore, selected, token);
            }
            catch (OperationCanceledException) { syncOutcome = "cancelled"; syncStatus = "修复已取消，已提交批次和备份保留，可重试。"; }
            catch (Exception error) when (error is not OutOfMemoryException) { syncOutcome = "failed"; syncStatus = "修复未完成，已保存记录与备份保留；请检查记录库后重试。"; }
            finally { Post("chat", new { type = "state", syncing = false, syncOutcome, syncStatus, syncDetail }); }
        }));
    }

}
