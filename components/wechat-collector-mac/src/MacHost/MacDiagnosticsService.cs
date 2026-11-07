using System.Text.Json;
using WechatUiCollector.Collection;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.Models;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;

namespace WechatCollector.Mac;

// This service reads the store selected by the caller. It never probes Windows UI,
// key stores, WeChat processes or screenshots to infer unavailable evidence.
public sealed class MacDiagnosticsService(SqliteMessageStore store, AppOptions options, string stateDirectory, string archiveDirectory, IRecentLogSource? recentLogs)
{
    readonly object snapshotLock = new();
    IReadOnlyList<CaptureGapRecord> gaps = [];
    IReadOnlyDictionary<string, object?> summary = new Dictionary<string, object?> { ["checkStatus"] = "notChecked", ["captureContinuity"] = "unknown", ["windowsUiObservation"] = "unavailable" };
    public string DatabasePath => store.DatabasePath;
    public string ArchivePath => Path.GetFullPath(archiveDirectory);
    public IReadOnlyList<CaptureGapRecord> Gaps { get { lock (snapshotLock) return gaps.ToArray(); } }
    public void InvalidateSnapshot(string status)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(status);
        lock (snapshotLock)
        {
            gaps = [];
            summary = new Dictionary<string, object?> { ["checkStatus"] = status, ["captureContinuity"] = "unknown", ["windowsUiObservation"] = "unavailable", ["invalidatedAt"] = DateTimeOffset.UtcNow };
        }
    }
    public async Task<object> ReadAsync(bool full, CancellationToken token)
    {
        if (full && token.IsCancellationRequested) InvalidateSnapshot("cancelled");
        token.ThrowIfCancellationRequested();
        if (!full)
        {
            var overview = await store.ReadOverviewAsync(token);
            return State($"更新于 {DateTime.Now:yyyy-MM-dd HH:mm:ss}", overview.SchemaVersion == overview.TargetSchemaVersion ? "版本一致" : "需要确认",
                "本页概况不代表完整性或采集连续性已检查。", Bytes(overview.DatabaseBytes + overview.WalBytes) + $" · v{overview.SchemaVersion}", "尚未盘点", "尚未盘点", "完整检查后显示", [], "采集连续性未知；完整检查会读取已保存的检查点及缺口记录。",
                [new("数据库结构", overview.SchemaVersion == overview.TargetSchemaVersion ? "版本一致" : "需要确认", $"当前 v{overview.SchemaVersion} / 目标 v{overview.TargetSchemaVersion}"), new("SQLite 完整性", "尚未检查", "打开页面不触发全库检查。"), new("采集连续性", "未知", "未取得当前 Mac 数据导入的完整性证明。")]);
        }
        InvalidateSnapshot("checking");
        try
        {
            var database = await store.GetDatabaseHealthAsync(token);
            var imported = await store.GetDbMessageImportStatsAsync(token);
            var recordedGaps = await store.QueryUnresolvedCaptureGapsAsync(null, 200, token);
            var attachments = await store.QueryAttachmentsAsync(null, token);
            var mediaRoot = ConfigurationLoader.ResolvePath(options.MediaDirectory, stateDirectory);
            token.ThrowIfCancellationRequested();
            var inventory = new AttachmentInventoryService(mediaRoot).BuildReport(attachments);
            var media = Scan([mediaRoot, Path.Combine(stateDirectory, "media"), Path.Combine(archiveDirectory, "media")], token);
            var logs = Scan([ConfigurationLoader.ResolvePath(options.LogDirectory, stateDirectory)], token);
            bool storageOk = database.SchemaVersion == database.TargetSchemaVersion && database.IntegrityOk;
            bool knownIssues = inventory.Summary.MissingFiles > 0 || inventory.Summary.UnsafePaths > 0 || database.UnresolvedCaptureGapCount > 0;
            string continuity = database.CaptureCheckpointCount == 0 ? "未知：没有已保存的旧采集检查点；不能由缺口数为零推断记录完整。" : $"已保存 {database.CaptureCheckpointCount:N0} 个旧采集检查点、{database.UnresolvedCaptureGapCount:N0} 个未解决缺口；不代表 Mac 导入来源已验证连续。";
            string gapSummary = recordedGaps.Count > 0 ? $"已保存 {database.UnresolvedCaptureGapCount:N0} 个未解决旧采集缺口；当前显示最新 {recordedGaps.Count:N0} 个。Mac 导入连续性仍未知。" : "没有已保存的未解决缺口；当前 Mac 导入采集连续性未知。";
            var details = new List<DiagnosticDetail> {
                new("数据库 Schema", database.SchemaVersion == database.TargetSchemaVersion ? "版本一致" : "需要修复", $"当前 v{database.SchemaVersion} / 目标 v{database.TargetSchemaVersion}"),
                new("SQLite 完整性", database.IntegrityOk ? "通过" : "异常", database.IntegrityResult),
                new("消息行统计", "已读取", $"Mac 导入 {imported.MessageCount:N0} 行、解析完成 {imported.ParsedCount:N0} 行；旧采集 {database.MessageCount:N0} 行、媒体记录 {database.MediaAssetCount:N0} 行。"),
                new("迁移备份", database.MigrationBackupCount > 0 ? "已保留" : "暂无", $"共 {database.MigrationBackupCount:N0} 份；最近 {database.LatestMigrationBackupAt?.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss") ?? "无记录"}"),
                new("采集连续性", "未知", continuity),
                new("旧消息节点解析", database.MessageParseObservationCount == 0 ? "未知" : "已记录", $"观察 {database.MessageParseObservationCount:N0} 次，节点 {database.RawMessageNodeCount:N0} 个，未产出 {database.DroppedMessageNodeCount:N0} 个；没有 Windows UI 样本时不评价 Mac 来源完整性。"),
                new("已登记附件", attachments.Count == 0 ? "覆盖未知" : "已盘点", $"登记 {attachments.Count:N0} 条，缺失 {inventory.Summary.MissingFiles:N0}，不安全路径 {inventory.Summary.UnsafePaths:N0}；未登记缓存不被判定为丢失消息。"),
                new("缓存目录", "已盘点", $"受配置管理的媒体目录及当前读取归档缓存共 {media.Count:N0} 个普通文件；跳过链接。"),
                new("Windows UI 会话摘要", "不可取得", "Mac 不具有原 Windows UI Automation 快照；未判断截断摘要、窗口恢复或 UI 回填能力。"),
                new("微信交互设置", options.AllowWeChatInteraction ? "已授权" : "只读设置", "仅报告保存的设置，不据此推断采集器正在运行或已具备 Windows 回填能力。")
            };
            var state = State($"检查时间：{DateTime.Now:yyyy-MM-dd HH:mm:ss}", !storageOk ? "需要修复" : knownIssues ? "需要关注" : "存储检查通过",
                "数据库完整性、实际保存的消息统计与普通缓存文件已检查；来源完整性和当前采集连续性没有可验证证明。", Bytes(database.DatabaseBytes + database.WalBytes) + $" · v{database.SchemaVersion}", $"{Bytes(media.Bytes)} · {media.Count:N0} 文件", $"{Bytes(logs.Bytes)} · {logs.Count:N0} 文件", $"{imported.MessageCount:N0} 导入 + {database.MessageCount:N0} 旧采集 / {database.MediaAssetCount:N0}", recordedGaps, gapSummary, details);
            lock (snapshotLock)
            {
                token.ThrowIfCancellationRequested();
                gaps = recordedGaps.ToArray();
                summary = new Dictionary<string, object?> { ["checkStatus"] = storageOk ? "storageChecked" : "repairNeeded", ["database"] = database, ["importedMessageCount"] = imported.MessageCount, ["attachmentMissingCount"] = inventory.Summary.MissingFiles, ["attachmentUnsafePathCount"] = inventory.Summary.UnsafePaths, ["mediaFileCount"] = media.Count, ["mediaBytes"] = media.Bytes, ["captureContinuity"] = "unknown", ["windowsUiObservation"] = "unavailable", ["checkedAt"] = DateTimeOffset.UtcNow };
            }
            return state;
        }
        catch (OperationCanceledException) { InvalidateSnapshot("cancelled"); throw; }
        catch { InvalidateSnapshot("failed"); throw; }
    }
    object State(string checkedAt, string overall, string detail, string dbSize, string mediaSize, string logSize, string recordCount, IReadOnlyList<CaptureGapRecord> currentGaps, string gapSummary, IReadOnlyList<DiagnosticDetail> details) => new {
        type = "healthState", checkedAt, overall, overallDetail = detail, risk = options.AllowWeChatInteraction ? "已保存主动交互授权；是否运行及平台支持范围需分别核实。" : "已保存只读模式设置。", dbSize, mediaSize, logSize, recordCount, gapSummary,
        gaps = currentGaps.Select(g => new { id = g.Id, conversation = g.Conversation, detectedAt = g.DetectedAt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss"), keyChange = $"{g.PreviousTail.Count} → {g.CurrentKeys.Count}", commitCount = $"{g.CandidateCount} / {g.InsertedCount}", hasReplay = g.ReplaySnapshot is not null }).ToArray(),
        details = details.Select(d => new { name = d.Name, status = d.Status, detail = d.Detail }).ToArray(), busy = false
    };
    public async Task ExportReplayAsync(string id, string destination, CancellationToken token)
    {
        var selected = Gaps.FirstOrDefault(g => g.Id == id);
        if (selected?.ReplaySnapshot is null) throw new ArgumentException("所选缺口没有已保存的脱敏回放，请重新检查或选择。");
        token.ThrowIfCancellationRequested();
        await AtomicWriteAsync(destination, async temporary => await ProtectedFileSystem.WriteAllTextAsync(temporary, JsonSerializer.Serialize(selected.ReplaySnapshot, new JsonSerializerOptions(JsonSerializerDefaults.Web) { WriteIndented = true }), token), token);
    }
    public async Task ExportBundleAsync(string destination, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        IReadOnlyDictionary<string, object?> current; lock (snapshotLock) current = new Dictionary<string, object?>(summary);
        var tail = DiagnosticBundleContext.ReadOnDiskLogTail(ConfigurationLoader.ResolvePath(options.LogDirectory, stateDirectory), 500).Select(MacDiagnosticsPrivacy.Scrub).ToArray();
        var records = recentLogs?.GetRecent(500).TakeLast(500).Select(MacDiagnosticsPrivacy.Record).ToArray() ?? [];
        await AtomicWriteAsync(destination, temporary => { DiagnosticBundleBuilder.Create(temporary, options, records, tail, current); return Task.CompletedTask; }, token);
    }
    async Task AtomicWriteAsync(string destination, Func<string, Task> write, CancellationToken token)
    {
        var target = MacOutputProtection.Resolve(destination, store.DatabasePath, stateDirectory, archiveDirectory,
            [ConfigurationLoader.ResolvePath(options.LogDirectory, stateDirectory), ConfigurationLoader.ResolvePath(options.MediaDirectory, stateDirectory),
             ConfigurationLoader.ResolvePath(options.JsonlOutputPath, stateDirectory), ConfigurationLoader.ResolvePath(options.AvatarCatalogPath, stateDirectory),
             Path.Combine(stateDirectory, "bridge-token"), Path.Combine(stateDirectory, "bridge-entry.json"), Path.Combine(stateDirectory, "bridge-errors.log"),
             Path.Combine(stateDirectory, "profile-ext-credentials.v1.json")]);
        var parent = Path.GetDirectoryName(target)!; ProtectedFileSystem.CreateDirectory(parent);
        string temporary = Path.Combine(parent, ".wechat-diagnostic-" + Guid.NewGuid().ToString("N") + ".tmp");
        try { await write(temporary); token.ThrowIfCancellationRequested(); ProtectedFileSystem.Move(temporary, target, overwrite: true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
    static (long Bytes, int Count) Scan(IEnumerable<string> roots, CancellationToken token)
    {
        long bytes = 0; int count = 0; var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var root in roots.Select(Path.GetFullPath).Distinct(StringComparer.Ordinal))
        {
            if (!Directory.Exists(root)) continue;
            if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0) throw new IOException("盘点目录是链接，未完成文件盘点。");
            foreach (var path in Directory.EnumerateFiles(root, "*", new EnumerationOptions { RecurseSubdirectories = true, AttributesToSkip = FileAttributes.ReparsePoint, IgnoreInaccessible = false }))
            { token.ThrowIfCancellationRequested(); if (seen.Add(Path.GetFullPath(path))) { bytes += new FileInfo(path).Length; count++; } }
        }
        return (bytes, count);
    }
    static string Bytes(long value) => value >= 1024 * 1024 ? $"{value / 1048576.0:F1} MB" : $"{value:N0} B";
    sealed record DiagnosticDetail(string Name, string Status, string Detail);
}
