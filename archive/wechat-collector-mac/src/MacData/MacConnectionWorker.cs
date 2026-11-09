using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace WechatCollector.Mac;

public sealed record MacConnectionEvent(string Event, string Account, string Operation, string State, string Cleanup, string Code, int Verified, int Missing)
{
    static readonly HashSet<string> States = ["authorizing", "bound", "running", "cancel_requested", "cleaning", "published", "published_partial", "cache_reused", "cancelled", "repair_required", "failed", "cleanup_unconfirmed"];
    static readonly HashSet<string> Codes = ["", "cancelled", "owner_lost", "timeout", "invalid_request", "work_failed", "publish_failed", "cleanup_unconfirmed", "verification_failed", "existing_partial", "existing_invalid", "invalid_archive"];
    public static MacConnectionEvent Parse(string raw, string account, string? operation)
    {
        if (Encoding.UTF8.GetByteCount(raw) > 4095) throw new IOException("连接响应无效。");
        using var doc = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 4 }); var value = doc.RootElement;
        string[] names = ["v", "event", "account", "operation", "state", "cleanup", "code", "verified", "missing"];
        var props = value.EnumerateObject().ToArray();
        if (props.Length != names.Length || props.Select(p => p.Name).Distinct().Count() != names.Length || props.Any(p => !names.Contains(p.Name)) || !value.GetProperty("v").TryGetInt32(out var v) || v != 1) throw new IOException("连接响应无效。");
        string Text(string key) => value.GetProperty(key).ValueKind == JsonValueKind.String ? value.GetProperty(key).GetString()! : throw new IOException("连接响应无效。");
        var result = new MacConnectionEvent(Text("event"), Text("account"), Text("operation"), Text("state"), Text("cleanup"), Text("code"), value.GetProperty("verified").GetInt32(), value.GetProperty("missing").GetInt32());
        if (result.Account != account || !Regex.IsMatch(result.Operation, "\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant) || operation is not null && result.Operation != operation || !States.Contains(result.State) || !Codes.Contains(result.Code) || result.Verified is < 0 or > 511 || result.Missing is < 0 or > 511 || result.Verified + result.Missing > 511 || result.Cleanup is not ("pending" or "complete" or "unconfirmed") || result.Event is not ("authorize" or "progress" or "terminal")) throw new IOException("连接响应无效。");
        if (result.Event == "authorize" && (result.State != "authorizing" || result.Cleanup != "pending" || result.Code != "") || result.Event != "terminal" && result.Cleanup != "pending" || result.Event == "terminal" && result.State is not ("published" or "published_partial" or "cache_reused" or "cancelled" or "repair_required" or "failed" or "cleanup_unconfirmed")) throw new IOException("连接响应无效。");
        return result;
    }
    public bool Usable => Event == "terminal" && State is "published" or "published_partial" or "cache_reused" && Cleanup == "complete" && Verified > 0;
}

public sealed record MacConnectionSettlement(string Account, string? Operation, string Cleanup);

// Duplex owned child. EOF revokes its relay; root/GUI processes are never killed here.
public sealed class MacConnectionWorker
{
    readonly TaskCompletionSource<MacConnectionSettlement> settlement = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public Task<MacConnectionSettlement> WorkerSettlement => settlement.Task;
    readonly SemaphoreSlim inputGate = new(1, 1);
    Process? child;
    volatile bool revoked, dispatched;
    string? nonce;
    public async Task SendStartAsync(string account, string operation)
    {
        await inputGate.WaitAsync();
        try
        {
            if (revoked || dispatched || operation != nonce || child is null || child.HasExited) throw new IOException("连接请求已过期。");
            dispatched = true;
            await child.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { v = 1, operation, account, command = "start" }));
            await child.StandardInput.FlushAsync();
        }
        finally { inputGate.Release(); }
    }
    public void Revoke()
    {
        lock (inputGate) { revoked = true; try { child?.StandardInput.Close(); } catch (Exception e) when (e is IOException or InvalidOperationException or ObjectDisposedException) { } }
    }
    public async Task<MacConnectionEvent> RunAsync(string worker, string account, string archive, Func<MacConnectionEvent, Task> onEvent, CancellationToken token)
    {
        try { return await RunOwnedAsync(worker, account, archive, onEvent, token); }
        finally { settlement.TrySetResult(new(account, nonce, "unconfirmed")); }
    }
    async Task<MacConnectionEvent> RunOwnedAsync(string worker, string account, string archive, Func<MacConnectionEvent, Task> onEvent, CancellationToken token)
    {
        if (!Path.IsPathFullyQualified(worker) || !File.Exists(worker) || !Regex.IsMatch(account, "\\A[A-Za-z0-9_-]{1,256}\\z", RegexOptions.CultureInvariant) || !Path.IsPathFullyQualified(archive)) throw new IOException("连接助手不可用。");
        var start = new ProcessStartInfo(worker) { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        start.ArgumentList.Add("--connect"); start.Environment.Clear(); start.Environment["PATH"] = "/usr/bin:/bin";
        using var process = new Process { StartInfo = start };
        token.ThrowIfCancellationRequested(); process.Start(); child = process;
        var exited = process.WaitForExitAsync(); // Sole process wait owner.
        using var errorsCancellation = new CancellationTokenSource();
        var errors = DiscardAsync(process.StandardError.BaseStream, errorsCancellation.Token);
        using var registration = token.Register(Revoke);
        var revokedSignal = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var revokeRegistration = token.Register(() => revokedSignal.TrySetResult());
        bool stdoutEOF = false, compromised = false, forced = false;
        MacConnectionEvent? terminal = null; bool authorized = false, ran = false; string previous = "authorizing";
        using var readerCancellation = new CancellationTokenSource(); Task? reader = null;
        try
        {
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { v = 1, account, archive }));
            await process.StandardInput.FlushAsync();
            reader = ReadEventsAsync();
            var first = await Task.WhenAny(reader, revokedSignal.Task, Task.Delay(TimeSpan.FromSeconds(365)));
            if (first != reader) { Revoke(); await reader.WaitAsync(TimeSpan.FromSeconds(8)); }
            else await reader;
            await exited.WaitAsync(TimeSpan.FromSeconds(8)); await errors.WaitAsync(TimeSpan.FromSeconds(1));
            if (terminal is null || process.ExitCode != (terminal.Usable ? 0 : terminal.State == "cancelled" ? 130 : 70)) throw new IOException("连接未完成。");
            token.ThrowIfCancellationRequested(); // Validated terminal remains available to finally on cancellation.
            return terminal;
            async Task ReadEventsAsync()
            {
                while (await ReadFrameAsync(process.StandardOutput.BaseStream, readerCancellation.Token) is { } raw)
                {
                    if (terminal is not null) throw new IOException("连接响应无效。");
                    var item = MacConnectionEvent.Parse(raw, account, nonce); nonce ??= item.Operation;
                    if (item.Event == "authorize") { if (authorized) throw new IOException("连接响应无效。"); authorized = true; }
                    if (item.Event == "progress")
                    {
                        bool valid = item.State switch
                        {
                            "bound" => previous == "authorizing" && dispatched && item.Code == "",
                            "running" => previous == "bound" && dispatched && item.Code == "",
                            "cancel_requested" => previous is "authorizing" or "bound" or "running",
                            "cleaning" => previous is "authorizing" or "bound" or "running" or "cancel_requested",
                            _ => false
                        };
                        if (!authorized || !valid) throw new IOException("连接响应无效。"); previous = item.State;
                    }
                    if (item.Event == "progress" && item.State == "running") { if (!dispatched) throw new IOException("连接响应无效。"); ran = true; }
                    if (item.Event == "terminal")
                    {
                        if (item.State is "published" or "published_partial" && (!authorized || !dispatched || !ran || !item.Usable) || item.State == "cache_reused" && (authorized || dispatched || !item.Usable)) throw new IOException("连接响应无效。");
                        terminal = item;
                    }
                    await onEvent(item);
                }
                stdoutEOF = true;
            }
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            // Cancellation AFTER a validated terminal is not a protocol failure.
            if (error is not OperationCanceledException || !token.IsCancellationRequested) compromised = true;
            throw;
        }
        finally
        {
            Revoke();
            bool exitedCleanly = false, readerSettled = false, errorsSettled = false;
            try
            {
                try { await exited.WaitAsync(TimeSpan.FromSeconds(8)); exitedCleanly = true; }
                catch (TimeoutException)
                {
                    compromised = true; forced = true;
                    try { if (!process.HasExited) process.Kill(entireProcessTree: false); } catch (InvalidOperationException) { }
                    try { await exited.WaitAsync(TimeSpan.FromSeconds(2)); }
                    catch (TimeoutException) { await exited; } // Retain the sole owner; a timeout is not a settled wait.
                }
                if (reader is not null)
                {
                    try { await reader.WaitAsync(TimeSpan.FromSeconds(2)); readerSettled = stdoutEOF; }
                    catch (Exception) { compromised = true; }
                }
                if (!readerSettled && reader is not null)
                {
                    readerCancellation.Cancel();
                    try { await reader; } catch (Exception) { compromised = true; }
                }
                try { await errors.WaitAsync(TimeSpan.FromSeconds(1)); errorsSettled = true; }
                catch (Exception)
                {
                    compromised = true; errorsCancellation.Cancel();
                    try { await errors; } catch (Exception) { }
                }
            }
            finally
            {
                child = null;
                bool expectedExit = exitedCleanly && terminal is not null && process.ExitCode == (terminal.Usable ? 0 : terminal.State == "cancelled" ? 130 : 70);
                bool complete = !compromised && !forced && expectedExit && readerSettled && errorsSettled &&
                    terminal!.Cleanup == "complete" && terminal.State != "cleanup_unconfirmed";
                settlement.TrySetResult(new(account, nonce, complete ? "complete" : "unconfirmed"));
            }
        }
    }

    static async Task<string?> ReadFrameAsync(Stream input, CancellationToken token)
    {
        var bytes = new List<byte>(4096); var one = new byte[1];
        while (await input.ReadAsync(one, token) > 0)
        {
            if (one[0] == 10) return new UTF8Encoding(false, true).GetString(bytes.ToArray());
            if (bytes.Count >= 4095) throw new IOException("连接响应过长。"); bytes.Add(one[0]);
        }
        if (bytes.Count != 0) throw new IOException("连接响应不完整。"); return null;
    }
    static async Task DiscardAsync(Stream input, CancellationToken token) { byte[] bytes = new byte[4096]; while (await input.ReadAsync(bytes, token) > 0) { } }
}
