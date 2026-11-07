using System.Diagnostics;
using System.Text;
using System.Text.Json;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// One owned child per source refresh. Cached-key import never launches wxkey/UI.
internal static class MacImportWorker
{
    internal static async Task<MacArchiveRefreshResult> RefreshAsync(string archive, string account, string sourceRoot, bool full, bool contacts, IProgress<string>? progress, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (PlaybackWorkCoordinator.Shared.IsActive) progress?.Report("播放期间已暂停后台更新，播放结束后继续…");
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        string project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
        string bundled = Path.GetFullPath(Path.Combine(project, "../worker/mac-worker"));
        var start = new ProcessStartInfo(File.Exists(bundled) ? bundled : (Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PYTHON") ?? "/usr/bin/python3")) { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        if (!File.Exists(bundled)) start.ArgumentList.Add(Path.Combine(project, "src/MacWorker/mac_worker.py"));
        start.Environment["PATH"] = Path.GetFullPath(Path.Combine(project, "../native")) + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        using var process = Process.Start(start) ?? throw new IOException("本地读取未启动。");
        void Stop() { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } }
        using var registration = token.Register(Stop);
        try
        {
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { action = "import", archive, account, sourceRoot, full, scope = contacts ? "contacts" : "messages" }).AsMemory(), token);
            process.StandardInput.Close();
            var outputTask = ReadBoundedAsync(process.StandardOutput, 1024 * 1024, token);
            var errorsTask = ReadProgressAsync(process.StandardError, progress, token);
            _ = outputTask.ContinueWith(task => { _ = task.Exception; if (task.IsFaulted) Stop(); }, TaskContinuationOptions.ExecuteSynchronously);
            _ = errorsTask.ContinueWith(task => { _ = task.Exception; if (task.IsFaulted) Stop(); }, TaskContinuationOptions.ExecuteSynchronously);
            await Task.WhenAll(outputTask, errorsTask); await process.WaitForExitAsync(token);
            if (process.ExitCode != 0) throw new IOException("本地读取未完成。");
            using var result = JsonDocument.Parse(await outputTask); var data = result.RootElement;
            if (Text(data, "state") != "done") throw new IOException("来源刷新未完成，已保存记录保持可读。");
            if (contacts)
            {
                if (!Flag(data, "sourceVerified") || Text(data, "sourceScope") != "contacts") throw new IOException("联系人来源校验未完成。");
                var files = Manifest(data, "sourceManifest", 1);
                if (files.Length != 1 || files[0].Path != "contact/contact.db" || files[0].EmptyNonMessage) throw new IOException("联系人来源清单无效。");
                return new("联系人来源已校验。", files);
            }
            if (!full)
            {
                int sourceCount = Number(data, "messageSourceCount"), failedCount = Number(data, "failedMessageDatabaseCount");
                if (!Flag(data, "messageCoverageChecked") || Text(data, "messageSourceScope") != "supported_message_databases" || sourceCount is < 1 or > 511 || failedCount < 0 || failedCount > sourceCount)
                    throw new IOException("消息来源覆盖情况未通过校验，未标记更新完成。");
                return new("", [], failedCount);
            }
            int sources = Number(data, "fullMessageDatabaseCount"), excluded = Number(data, "excludedNonMessageDatabaseCount"), empty = Number(data, "emptyNonMessageDatabaseCount");
            if (!Flag(data, "full") || !Flag(data, "fullSourceVerified") || Text(data, "fullSourceScope") != "supported_message_databases" || sources <= 0 || excluded < 0 || empty < 0 || empty > excluded || sources > 511 || empty > 510)
                throw new IOException("读取助手尚未完成全面解析来源检查。");
            var manifest = Manifest(data, "fullSourceManifest", 512);
            if (manifest.Length != sources + 1 + empty || manifest.Count(file => file.EmptyNonMessage) != empty) throw new IOException("关键来源清单与覆盖范围不符。");
            return new($"范围：受支持消息库 {sources:N0} 个；排除非消息库 {excluded:N0} 个（空结构 {empty:N0} 个）。不代表账号全部内容。", manifest);
        }
        finally { Stop(); }
    }
    static MacArchiveSourceFile[] Manifest(JsonElement data, string name, int maximum)
    {
        if (!data.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array || value.GetArrayLength() is < 1 || value.GetArrayLength() > maximum) throw new IOException("来源清单无效。");
        return JsonSerializer.Deserialize<MacArchiveSourceFile[]>(value.GetRawText(), new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? throw new IOException("来源清单无法读取。");
    }
    static string Text(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind == JsonValueKind.String ? item.GetString()! : "";
    static bool Flag(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind == JsonValueKind.True;
    static int Number(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.TryGetInt32(out var number) ? number : -1;
    static async Task<string> ReadBoundedAsync(StreamReader reader, int limit, CancellationToken token)
    {
        var text = new StringBuilder(); var buffer = new char[4096]; int count;
        while ((count = await reader.ReadAsync(buffer, token)) > 0) { if (text.Length + count > limit) throw new IOException("本地读取响应过长。"); text.Append(buffer, 0, count); }
        return text.ToString();
    }
    static async Task ReadProgressAsync(StreamReader reader, IProgress<string>? progress, CancellationToken token)
    {
        var line = new StringBuilder(); var buffer = new char[1024]; int count; bool overflow = false;
        while ((count = await reader.ReadAsync(buffer, token)) > 0)
            for (int i = 0; i < count; i++)
            {
                if (buffer[i] != '\n') { if (line.Length < 16384) line.Append(buffer[i]); else overflow = true; continue; }
                if (!overflow) try { using var data = JsonDocument.Parse(line.ToString()); var phase = Text(data.RootElement, "phase"); if (phase.Length > 0) progress?.Report(phase); } catch (JsonException) { }
                line.Clear(); overflow = false;
            }
    }
}
