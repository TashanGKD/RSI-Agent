using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace WechatCollector.Mac;

// Two private local workers amortize one-file extraction during scrolling and
// batch transcription. Each process has exactly one request in flight.
public sealed class MacWorkerPool : IDisposable
{
    readonly SemaphoreSlim slots;
    public MacWorkerPool(int capacity = 2)
    {
        if (capacity is < 1 or > 2) throw new ArgumentOutOfRangeException(nameof(capacity));
        slots = new(capacity);
    }
    readonly ConcurrentBag<Process> idle = new();
    readonly ConcurrentDictionary<Process, byte> workers = new();
    int stopped;
    readonly object lifecycle = new();
    Process Start()
    {
        string project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
        string bundled = Path.GetFullPath(Path.Combine(project, "../worker/mac-worker"));
        var start = new ProcessStartInfo(File.Exists(bundled) ? bundled : (Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PYTHON") ?? "/usr/bin/python3")) { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        if (!File.Exists(bundled)) start.ArgumentList.Add(Path.Combine(project, "src/MacWorker/mac_worker.py"));
        start.ArgumentList.Add("--serve");
        start.Environment["PATH"] = Path.GetFullPath(Path.Combine(project, "../native")) + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        var process = Process.Start(start) ?? throw new IOException("本地附件读取未启动。");
        process.StandardInput.AutoFlush = true; workers[process] = 0;
        _ = Task.Run(async () => { try { var discard = new char[1024]; while (await process.StandardError.ReadAsync(discard) > 0) { } } catch (Exception error) when (error is IOException or ObjectDisposedException or InvalidOperationException) { } });
        return process;
    }
    void Remove(Process process)
    {
        try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { }
        workers.TryRemove(process, out _);
        process.Dispose();
    }
    public async Task<string> ExchangeAsync(object request, CancellationToken token)
    {
        await slots.WaitAsync(token); Process? process = null; bool healthy = false;
        try
        {
            lock (lifecycle)
            {
                ObjectDisposedException.ThrowIf(stopped != 0, this);
                while (idle.TryTake(out var candidate)) { if (!candidate.HasExited) { process = candidate; break; } Remove(candidate); }
                process ??= Start();
            }
            using var cancel = token.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(request).AsMemory(), token);
            var output = new StringBuilder(); var character = new char[1];
            while (await process.StandardOutput.ReadAsync(character, token) > 0)
            {
                if (character[0] == '\n')
                {
                    using var json = JsonDocument.Parse(output.ToString());
                    if (json.RootElement.ValueKind != JsonValueKind.Object) throw new IOException("本地附件响应无效。");
                    healthy = true; return output.ToString();
                }
                if (output.Length >= 32768) throw new IOException("本地附件响应超出允许范围。");
                output.Append(character[0]);
            }
            throw new IOException("本地附件读取中断，请重试。");
        }
        finally
        {
            if (process is not null)
            {
                if (healthy && !token.IsCancellationRequested && Volatile.Read(ref stopped) == 0 && !process.HasExited) idle.Add(process);
                else Remove(process);
            }
            slots.Release();
        }
    }
    public void Dispose()
    {
        lock (lifecycle)
        {
            if (Interlocked.Exchange(ref stopped, 1) != 0) return;
            foreach (var process in workers.Keys) { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } }
        }
    }
}
