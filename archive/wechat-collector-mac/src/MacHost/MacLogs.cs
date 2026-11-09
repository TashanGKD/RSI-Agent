using System.Text.Json;
using WechatUiCollector.Diagnostics;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    CancellationTokenSource? liveLogsCancellation;
    bool logsVisible;
    void SetLogsVisible(bool visible)
    {
        logsVisible = visible;
        liveLogsCancellation?.Cancel(); liveLogsCancellation?.Dispose(); liveLogsCancellation = null;
        if (!visible) return;
        long sequence = (recentLogs?.GetRecent(1).LastOrDefault()?.Sequence) ?? 0;
        long failures = (recentLogs as StructuredAppLogger)?.WriteFailureCount ?? 0;
        Post("settings", LogsState());
        var cancellation = OperationCancellation(); liveLogsCancellation = cancellation;
        var token = cancellation.Token;
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                while (true)
                {
                    await Task.Delay(1000, token);
                    await gate.WaitAsync(token);
                    try
                    {
                        if (!logsVisible || selectedTab != "SettingsTab") continue;
                        long next = (recentLogs?.GetRecent(1).LastOrDefault()?.Sequence) ?? 0;
                        long nextFailures = (recentLogs as StructuredAppLogger)?.WriteFailureCount ?? 0;
                        if (next != sequence || nextFailures != failures)
                        {
                            Post("settings", LogsState()); sequence = next; failures = nextFailures;
                        }
                    }
                    finally { gate.Release(); }
                }
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        }));
    }
    void StopLiveLogs() { logsVisible = false; liveLogsCancellation?.Cancel(); }
    object LogsState()
    {
        // Preserve MainWindow.RefreshRecentLogs' original payload and newest-first
        // ordering. Reuse the original privacy filter for injected sources as well.
        var records = (recentLogs?.GetRecent(500) ?? Array.Empty<AppLogRecord>()).TakeLast(500).ToArray();
        long failures = (recentLogs as StructuredAppLogger)?.WriteFailureCount ?? 0;
        return new
        {
            type = "logsState",
            summary = $"本次运行 {records.Length:N0} 条 · 最新在前" + (failures > 0 ? $" · 日志落盘失败 {failures} 次，内存记录仍可查看" : ""),
            logs = records.Select(record =>
            {
                var message = MacDiagnosticsPrivacy.Scrub(record.Message);
                return new
                {
                    seq = record.Sequence,
                    time = record.TimestampUtc.ToLocalTime().ToString("HH:mm:ss"),
                    level = record.Level.ToString(),
                    @event = record.EventId,
                    component = record.Component,
                    message,
                    details = $"时间 {record.TimestampUtc.ToLocalTime():yyyy-MM-dd HH:mm:ss.fff} · 级别 {record.Level} · 事件 {record.EventId} · 组件 {record.Component} · 操作 {record.OperationId ?? "-"}\n{message}\n{MacDiagnosticsPrivacy.Scrub(JsonSerializer.Serialize(LogPrivacy.Properties(record.Properties)))}"
                };
            }).Reverse().ToArray()
        };
    }
}
