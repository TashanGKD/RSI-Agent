using System.Text.Json;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    MacDiagnosticsService? diagnosticsService;
    AppOptions? diagnosticsOptions;
    object? lastDiagnosticsState;
    Task diagnosticsWork = Task.CompletedTask;
    CancellationTokenSource? diagnosticsCancellation;
    bool diagnosticsPending;
    readonly Dictionary<string, (MacDiagnosticsService Service, string? GapId, string Page)> diagnosticExports = new();
    public bool DiagnosticsBusy => diagnosticsPending;
    MacDiagnosticsService DiagnosticsService()
    {
        var options = Options;
        if (diagnosticsService is null || diagnosticsService.DatabasePath != store.DatabasePath || diagnosticsService.ArchivePath != Path.GetFullPath(archive) || !ReferenceEquals(diagnosticsOptions, options))
        {
            diagnosticsService = new(store, options, directory, archive, recentLogs);
            diagnosticsOptions = options; lastDiagnosticsState = null;
        }
        return diagnosticsService;
    }
    public async Task<object> ReadDiagnosticsOverviewAsync(CancellationToken token)
    {
        var service = DiagnosticsService();
        return lastDiagnosticsState ?? await service.ReadAsync(false, token);
    }
    public async Task DiagnosticsActionAsync(string page, string action, JsonElement command, CancellationToken token)
    {
        switch (action)
        {
            case "ready": case "healthOverview":
                Post(page, await ReadDiagnosticsOverviewAsync(token)); return;
            case "refreshHealth":
                if (DiagnosticsBusy) return;
                var service = DiagnosticsService();
                diagnosticsCancellation?.Dispose();
                var cancellation = OperationCancellation(); diagnosticsCancellation = cancellation; diagnosticsPending = true;
                var checkToken = cancellation.Token;
                Post(page, DiagnosticProgress("正在检查", "正在检查数据库完整性与实际保存的数据；可取消，其他页面仍可使用。", true));
                diagnosticsWork = TrackShutdownTask(Task.Run(async () =>
                {
                    object result;
                    try { result = await service.ReadAsync(true, checkToken); }
                    catch (OperationCanceledException) { service.InvalidateSnapshot("cancelled"); result = DiagnosticProgress("未完成检查", "检查已取消；取消不被记录为通过。", false); }
                    catch (Exception error) when (error is not OutOfMemoryException)
                    {
                        service.InvalidateSnapshot("failed");
                        RuntimeEventSource.Emit(AppLogLevel.Error, "MAC_HEALTH_CHECK_FAILED", "MacDiagnostics", "本地诊断检查未完成。", new Dictionary<string, object?> { ["errorType"] = error.GetType().Name });
                        result = DiagnosticProgress("检查不可用", "完整检查未完成；请查看运行日志后重试。", false);
                    }
                    await gate.WaitAsync();
                    try
                    {
                        // Publish completion and retire cancellation in the same command
                        // transaction. Task.IsCompleted lags behind this publication.
                        if (ReferenceEquals(diagnosticsCancellation, cancellation)) { diagnosticsPending = false; diagnosticsCancellation = null; }
                        if (ReferenceEquals(service, diagnosticsService) && service.DatabasePath == store.DatabasePath)
                        {
                            if (service.ArchivePath != Path.GetFullPath(archive)) { service.InvalidateSnapshot("sourceChanged"); result = DiagnosticProgress("未完成检查", "读取归档已切换，请重新检查。", false); }
                            else if (checkToken.IsCancellationRequested) { service.InvalidateSnapshot("cancelled"); result = DiagnosticProgress("未完成检查", "检查已取消；取消不被记录为通过。", false); }
                            lastDiagnosticsState = result; Post(page, result);
                        }
                        else service.InvalidateSnapshot("superseded");
                    }
                    finally { gate.Release(); cancellation.Dispose(); }
                })); return;
            case "cancelHealth":
                if (!diagnosticsPending) return;
                if (diagnosticsCancellation is { } activeCheck) TryCancel(activeCheck);
                diagnosticsService?.InvalidateSnapshot("cancelled"); return;
            case "selectGap":
                if (!DiagnosticsService().Gaps.Any(g => g.Id == Text(command, "id"))) throw new ArgumentException("缺口选择已过期，请重新检查。");
                Post(page, await ReadDiagnosticsOverviewAsync(token)); return;
            case "openLogs":
                selectedTab = "SettingsTab"; Post("navigation", new { type = "macNavigation", id = selectedTab });
                Post("settings", new { type = "settingsSection", section = "logs" }); SetLogsVisible(true); return;
            case "exportDiagnostics": case "exportGapReplay":
                var exporter = DiagnosticsService(); string? gapId = null;
                if (action == "exportGapReplay")
                {
                    gapId = Text(command, "id");
                    if (!exporter.Gaps.Any(g => g.Id == gapId && g.ReplaySnapshot is not null)) throw new ArgumentException("所选缺口没有可导出的已保存脱敏回放。");
                }
                string requestId = "diagnostic-" + Guid.NewGuid().ToString("N");
                if (diagnosticExports.Count >= 16) throw new ArgumentException("待选择的诊断导出过多，请完成或取消已有选择。");
                diagnosticExports.Add(requestId, (exporter, gapId, page));
                Post(page, new { type = "macNative", command = "saveDocument", page = "settings", requestId, title = gapId is null ? "导出脱敏诊断包" : "导出脱敏采集回放", filename = $"wechat-{(gapId is null ? "diagnostics" : "capture-replay")}-{DateTime.Now:yyyyMMdd-HHmmss}.{(gapId is null ? "zip" : "json")}" }); return;
            case "saveDocument":
                if (!diagnosticExports.Remove(Text(command, "requestId"), out var pending)) throw new ArgumentException("诊断导出选择已过期，请重新发起。");
                string path = Text(command, "path"); if (path.Length == 0) return;
                var activeExporter = DiagnosticsService();
                if (!ReferenceEquals(pending.Service, activeExporter) || pending.Service.DatabasePath != store.DatabasePath || pending.Service.ArchivePath != Path.GetFullPath(archive))
                    throw new ArgumentException("诊断来源或设置已改变，请重新发起导出。");
                // The save operation is bounded to logs/summary or one redacted replay;
                // source data and the selected destination are protected by the service.
                if (pending.GapId is null) await pending.Service.ExportBundleAsync(path, token);
                else await pending.Service.ExportReplayAsync(pending.GapId, path, token);
                Post(pending.Page, new { type = "macNative", command = "notice", text = pending.GapId is null ? "已导出脱敏诊断包；不含聊天库、原文、附件或凭据。" : "已导出已保存的脱敏采集回放。" }); return;
            case "backfillGap":
                if (!DiagnosticsService().Gaps.Any(g => g.Id == Text(command, "id"))) throw new ArgumentException("缺口选择已过期，请重新检查。");
                selectedTab = "HistoryExportTab"; Post("navigation", new { type = "macNavigation", id = selectedTab });
                Post(page, new { type = "macNative", command = "notice", text = "已转到历史导出页。此缺口来自旧采集检查点；Mac 本地导入不能替代原 Windows UI 历史回填，未执行或标记缺口恢复。" }); return;
            default: throw new ArgumentException("未知诊断操作。");
        }
    }
    static object DiagnosticProgress(string overall, string detail, bool busy) => new { type = "healthState", checkedAt = busy ? "正在检查本地状态…" : $"更新于 {DateTime.Now:yyyy-MM-dd HH:mm:ss}", overall, overallDetail = detail, risk = "", dbSize = "", mediaSize = "", logSize = "", recordCount = "", gapSummary = "采集连续性未知；未完成的检查不构成完整性证明。", gaps = Array.Empty<object>(), details = Array.Empty<object>(), busy };
    public void StopDiagnostics()
    {
        if (diagnosticsCancellation is { } activeCheck) TryCancel(activeCheck); StopLiveLogs();
    }
}
