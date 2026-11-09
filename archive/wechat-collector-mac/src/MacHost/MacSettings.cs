using System.Text.Json;
using WechatUiCollector.WechatDb;
using WechatUiCollector.Configuration;
using WechatUiCollector.Storage;
using WechatUiCollector.Safety;
using System.Diagnostics;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    string theme = "system";
    AppOptions? savedOptions;
    string backupSummary = "";
    string[] backupDetails = [];
    string? pendingDatabasePath, pendingAttachmentSourceDirectory;
    AppOptions Options => savedOptions ??= File.Exists(Path.Combine(directory, "settings.json")) ? ConfigurationLoader.LoadOptions(Path.Combine(directory, "settings.json")) : ConfigurationLoader.LoadDefaultOptions() with { DatabasePath = store.DatabasePath, JsonlOutputPath = Path.Combine(directory, "messages.jsonl"), LogDirectory = Path.Combine(directory, "logs"), MediaDirectory = Path.Combine(directory, "media"), LocalChatAutoUpdateMinutes = 0, LocalChatSetupState = "pending", AllowWeChatInteraction = false };
    void SaveOptions(AppOptions options) { ConfigurationLoader.SaveOptions(options, Path.Combine(directory, "settings.json")); savedOptions = options; }
    static bool Flag(JsonElement command, string property) => command.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.True;
    static int Number(JsonElement command, string property, int fallback) => command.TryGetProperty(property, out var value) && value.TryGetInt32(out var number) ? number : fallback;
    async Task SettingsAsync(string action, JsonElement command, CancellationToken token)
    {
        switch (action)
        {
            case "ready": theme = Options.ThemeMode; Post("settings", new { type = "macNative", command = "theme", mode = theme }); break;
            case "settingsSection":
                if (Text(command, "section") == "logs") { SetLogsVisible(true); return; }
                SetLogsVisible(false);
                break;
            case "theme":
                string mode = Text(command, "mode"); if (!new[] { "system", "light", "dark" }.Contains(mode)) throw new ArgumentException("未知主题。");
                theme = mode; SaveOptions(Options with { ThemeMode = mode });
                Post("settings", new { type = "macNative", command = "theme", mode = theme }); break;
            case "openVoiceSettings":
                selectedTab = "LocalChatsTab";
                Post("navigation", new { type = "macNavigation", id = selectedTab });
                Post("navigation", new { type = "navigation", selected = selectedTab, items = Tabs });
                Post("chat", new { type = "openVoice" });
                return;
            case "openDataDirectory": Post("settings", new { type = "macNative", command = "openFolder", path = directory }); break;
            case "openReleaseNotes": Post("settings", new { type = "macNative", command = "openUrl", url = "https://github.com/gqy20/wechat-ui-collector/releases" }); break;
            case "openLicenses": Post("settings", new { type = "macNative", command = "openLicenses" }); break;
            case "healthOverview": case "refreshHealth": case "cancelHealth": case "openLogs": case "exportDiagnostics": case "selectGap": case "exportGapReplay": case "backfillGap": case "saveDocument":
                await DiagnosticsActionAsync("settings", action, command, token); return;
            case "backupPreview":
                var backups = store.PreviewBackups(); backupSummary = $"已找到 {backups.Count} 份备份。"; backupDetails = backups.Select(b => b.ToString()).ToArray(); break;
            case "selectRecordDirectory": case "selectAttachmentSource":
                Post("settings", new { type = "macNative", command = "selectFolder", page = "settings", field = action == "selectRecordDirectory" ? "databasePath" : "attachmentSourceDirectory" }); break;
            case "selectedFolder":
                string folder = Text(command, "path");
                if (folder.Length == 0) return;
                string selectedField = Text(command, "field");
                if (selectedField is not ("databasePath" or "attachmentSourceDirectory")) throw new ArgumentException("未知目录选项。");
                string selectedFolder = Path.GetFullPath(folder);
                if (selectedField == "databasePath") pendingDatabasePath = Path.Combine(selectedFolder, "records.db");
                else pendingAttachmentSourceDirectory = selectedFolder;
                break;
            case "save":
                var candidate = Options with {
                    DatabasePath = Path.GetFullPath(Text(command, "databasePath")), BackupRetentionCount = Number(command, "backupRetentionCount", Options.BackupRetentionCount),
                    AttachmentSourceDirectory = Text(command, "attachmentSourceDirectory"), AttachmentSourceSearchSubdirectories = Flag(command, "attachmentSourceRecursive"),
                    AllowWeChatInteraction = Flag(command, "allowWeChatInteraction"), EnableBackgroundWindowRecovery = Flag(command, "backgroundWindowRecovery"), EnableUnreadConversationOpening = Flag(command, "enableOpening"),
                    ReturnToOriginalConversationAfterAutoOpen = Flag(command, "returnOriginal"), MinimumUserIdleBeforeInteractionMilliseconds = Number(command, "userIdleThreshold", 3000),
                    EnableWindowMessageClickFallbackForWhitelist = Flag(command, "windowMessageFallback"), EnableMouseClickFallbackForWhitelist = Flag(command, "mouseFallback"), EnableHistoryBackfill = Flag(command, "historyBackfill"), EnableMergedForwardExpansion = Flag(command, "mergedForwardExpansion"), EnableAttachmentImport = Flag(command, "attachmentImport") };
                if (candidate.MinimumUserIdleBeforeInteractionMilliseconds < 0) throw new ArgumentException("等待空闲时间不能为负数。");
        if (candidate.DatabasePath != store.DatabasePath) await ChangeStorageAsync(candidate.DatabasePath, candidate.BackupRetentionCount, token);
                else if (candidate.BackupRetentionCount != Options.BackupRetentionCount) store = new SqliteMessageStore(store.DatabasePath, candidate.BackupRetentionCount);
                SaveOptions(candidate); pendingDatabasePath = pendingAttachmentSourceDirectory = null; feedback = "设置已保存。"; break;
            case "autoUpdate":
                int interval = Number(command, "minutes", -1); if (!new[] { 0, 5, 10, 15, 30 }.Contains(interval)) throw new ArgumentException("更新间隔无效。");
                SaveOptions(Options with { LocalChatAutoUpdateMinutes = interval }); ConfigureAutoUpdate(interval); break;
            default: throw new NotSupportedException("此功能的 Mac 适配尚未完成，未执行操作。");
        }
        var options = Options;
        Post("settings", new { type = "state", version = "0.2.5 Mac 开发版", wechatVersion = WechatVersion(), autoUpdateMinutes = options.LocalChatAutoUpdateMinutes, voiceModelPath = LocalTranscriber.ModelPath, voiceModelPresent = File.Exists(LocalTranscriber.ModelPath), sourceAvailable = Directory.Exists(archive), theme, databasePath = pendingDatabasePath ?? store.DatabasePath, backupRetentionCount = options.BackupRetentionCount, storageStatus = feedback,
            attachmentSourceDirectory = pendingAttachmentSourceDirectory ?? options.AttachmentSourceDirectory, attachmentSourceRecursive = options.AttachmentSourceSearchSubdirectories, attachmentSourceAutoDiscovered = "", allowWeChatInteraction = options.AllowWeChatInteraction, backgroundWindowRecovery = options.EnableBackgroundWindowRecovery, enableOpening = options.EnableUnreadConversationOpening, returnOriginal = options.ReturnToOriginalConversationAfterAutoOpen, userIdleThreshold = options.MinimumUserIdleBeforeInteractionMilliseconds, windowMessageFallback = options.EnableWindowMessageClickFallbackForWhitelist, mouseFallback = options.EnableMouseClickFallbackForWhitelist, historyBackfill = options.EnableHistoryBackfill, mergedForwardExpansion = options.EnableMergedForwardExpansion, attachmentImport = options.EnableAttachmentImport,
            runtimeHint = options.AllowWeChatInteraction ? "已授权主动操作；采集时采用保存的设置。" : "只读模式。", collectorRunning = false, busy = false, backupSummary, backupDetails });
    }
    async Task ChangeStorageAsync(string destination, int retention, CancellationToken token, Action<string>? saveSetting = null)
    {
        if (exportBusy || DiagnosticsBusy || !voiceWork.IsCompleted || !syncWork.IsCompleted || official?.Busy == true) throw new ArgumentException("请先等待当前更新、导出或转写完成，再更改保存位置。");
        var path = SourcePathProtection.DatabasePath(destination);
        if (File.Exists(path)) throw new ArgumentException("目标位置已有记录库，请选择一个新的文件位置，避免覆盖已有记录。");
        knowledgeCancellation?.Cancel();
        try { await knowledgeWork.WaitAsync(token); } catch (OperationCanceledException) when (!token.IsCancellationRequested) { }
        if (saveSetting is not null)
        {
            var prepared = new SqliteMessageStore(path, retention);
            await RecordStorageRelocator.RelocateAsync(store.DatabasePath, path, saveSetting, null, token);
            store = prepared; feedback = "记录已复制到新位置，原记录保留。"; return;
        }
        ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(path)!);
        await using var source = new Microsoft.Data.Sqlite.SqliteConnection("Data Source=" + store.DatabasePath);
        await source.OpenAsync(token); await using var target = new Microsoft.Data.Sqlite.SqliteConnection("Data Source=" + path); await target.OpenAsync(token);
        source.BackupDatabase(target); await target.CloseAsync();
        var next = new SqliteMessageStore(path, retention); await next.EnsureReadyForReadingAsync(token);
        if (await next.CheckIntegrityAsync(token) != "ok") throw new IOException("新位置校验未通过，原记录已保留。");
        store = next; feedback = "记录已复制到新位置，原记录保留。";
    }
    static string WechatVersion()
    {
        var start = new ProcessStartInfo("/usr/bin/plutil") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (var value in new[] { "-extract", "CFBundleShortVersionString", "raw", "/Applications/WeChat.app/Contents/Info.plist" }) start.ArgumentList.Add(value);
        try { using var process = Process.Start(start)!; var version = process.StandardOutput.ReadToEnd().Trim(); process.WaitForExit(); return process.ExitCode == 0 ? version : "未检测到"; } catch (IOException) { return "未检测到"; }
    }
}
