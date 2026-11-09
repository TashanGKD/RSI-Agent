using System.Diagnostics;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace WechatUiCollector.Safety;

internal static class MacCredentialProtection
{
    static readonly byte[] Header = Encoding.ASCII.GetBytes("MACGCM1");
    const int MasterKeyBytes = 32, CleanupMilliseconds = 1000;
    enum HelperFailure { None, Start, Stdout, Stderr, Exit, Timeout, Communication, Cleanup, Cancelled }

    static byte[] MasterKey(MacVaultProcessLimits limits)
    {
        ArgumentNullException.ThrowIfNull(limits); limits.Validate();
        string? helper = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_VAULT");
        helper ??= Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../native/mac-vault"));
        if (!File.Exists(helper)) throw new CryptographicException("本地钥匙串组件未就绪。");
        return ReadMasterKeyAsync(helper,limits).GetAwaiter().GetResult();
    }

    static async Task<byte[]> ReadMasterKeyAsync(string helper, MacVaultProcessLimits limits)
    {
        byte[] stdout = new byte[MasterKeyBytes + 1]; // A single sentinel proves oversize.
        byte[] stderr = new byte[Math.Min(1024,limits.MaximumStderrBytes + 1)];
        byte[]? key = null;
        using var budget = new CancellationTokenSource(limits.Timeout);
        var process = new Process { StartInfo = new ProcessStartInfo(helper) {
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true
        } };
        var operations = new List<Task<HelperFailure>>();
        HelperFailure failure = HelperFailure.None;
        try
        {
            if (budget.IsCancellationRequested) failure = HelperFailure.Timeout;
            else
            {
                try { if (!process.Start()) failure = HelperFailure.Start; }
                catch { failure = HelperFailure.Start; }
            }
            if (failure == HelperFailure.None)
            {
                // All three operations share one deadline. WhenAny observes a
                // failing pipe immediately rather than awaiting the other pipe/exit.
                Task<HelperFailure> output = ReadStdoutAsync(process.StandardOutput.BaseStream,stdout,budget.Token);
                operations.Add(output);
                Task<HelperFailure> errors = ReadStderrAsync(process.StandardError.BaseStream,stderr,limits.MaximumStderrBytes,budget.Token);
                operations.Add(errors);
                Task<HelperFailure> exit = WaitForHelperAsync(process,budget.Token);
                operations.Add(exit);
                var pending = operations.ToList();
                Task expired = Task.Delay(System.Threading.Timeout.InfiniteTimeSpan,budget.Token);
                while (pending.Count != 0 && failure == HelperFailure.None)
                {
                    Task completed = await Task.WhenAny(pending.Cast<Task>().Append(expired)).ConfigureAwait(false);
                    if (completed == expired || budget.IsCancellationRequested) { failure = HelperFailure.Timeout; break; }
                    var finished = (Task<HelperFailure>)completed;
                    failure = await finished.ConfigureAwait(false); pending.Remove(finished);
                }
                if (budget.IsCancellationRequested) failure = HelperFailure.Timeout;
                if (failure == HelperFailure.None) key = stdout.AsSpan(0,MasterKeyBytes).ToArray();
            }
        }
        catch { failure = HelperFailure.Communication; }
        finally
        {
            bool cleaned = false;
            try { cleaned = await CleanupAsync(process,budget,operations).ConfigureAwait(false); }
            catch { /* Cleanup errors are classified without transport details. */ }
            finally
            {
                CryptographicOperations.ZeroMemory(stdout); CryptographicOperations.ZeroMemory(stderr);
                try { process.Dispose(); } catch { cleaned = false; }
            }
            if (!cleaned) failure = HelperFailure.Cleanup;
        }
        if (failure != HelperFailure.None || key is null)
        {
            if (key is not null) CryptographicOperations.ZeroMemory(key);
            throw Failure(failure);
        }
        return key;
    }

    static async Task<HelperFailure> ReadStdoutAsync(Stream source, byte[] buffer, CancellationToken token)
    {
        try
        {
            int used = 0;
            while (true)
            {
                int count = await source.ReadAsync(buffer.AsMemory(used,buffer.Length - used),token).ConfigureAwait(false);
                if (count == 0) return used == MasterKeyBytes ? HelperFailure.None : HelperFailure.Stdout;
                used += count;
                if (used > MasterKeyBytes) return HelperFailure.Stdout;
            }
        }
        catch (OperationCanceledException) { return HelperFailure.Cancelled; }
        catch { return HelperFailure.Communication; }
    }

    static async Task<HelperFailure> ReadStderrAsync(Stream source, byte[] buffer, int maximum, CancellationToken token)
    {
        try
        {
            int used = 0;
            while (true)
            {
                int wanted = Math.Min(buffer.Length,maximum - used + 1);
                int count = await source.ReadAsync(buffer.AsMemory(0,wanted),token).ConfigureAwait(false);
                if (count == 0) return HelperFailure.None;
                used += count;
                if (used > maximum) return HelperFailure.Stderr;
            }
        }
        catch (OperationCanceledException) { return HelperFailure.Cancelled; }
        catch { return HelperFailure.Communication; }
    }

    static async Task<HelperFailure> WaitForHelperAsync(Process process, CancellationToken token)
    {
        try
        {
            await process.WaitForExitAsync(token).ConfigureAwait(false);
            return process.ExitCode == 0 ? HelperFailure.None : HelperFailure.Exit;
        }
        catch (OperationCanceledException) { return HelperFailure.Cancelled; }
        catch { return HelperFailure.Communication; }
    }

    static async Task<bool> CleanupAsync(Process process, CancellationTokenSource budget, IReadOnlyList<Task<HelperFailure>> operations)
    {
        bool ok = true, associated = false;
        var clock = Stopwatch.StartNew();
        int Remaining() => Math.Max(0,CleanupMilliseconds - (int)clock.ElapsedMilliseconds);
        try { budget.Cancel(); } catch { ok = false; }
        // Only this Process instance was created by this call. No global PID,
        // process-name, group or descendant scans are performed.
        try { _ = process.Id; associated = true; } catch (InvalidOperationException) { } catch { ok = false; }
        if (associated)
        {
            try { if (!process.HasExited) process.Kill(); }
            catch (InvalidOperationException) { /* Exit can race the direct-child kill. */ }
            catch { ok = false; }
            try { if (!process.WaitForExit(Remaining())) ok = false; } catch { ok = false; }
            try { process.StandardOutput.Dispose(); } catch { ok = false; }
            try { process.StandardError.Dispose(); } catch { ok = false; }
        }
        if (operations.Count != 0)
        {
            try
            {
                Task completed = Task.WhenAll(operations);
                if (completed.IsCompleted) await completed.ConfigureAwait(false);
                else await completed.WaitAsync(TimeSpan.FromMilliseconds(Math.Max(1,Remaining()))).ConfigureAwait(false);
            }
            catch { ok = false; }
        }
        return ok;
    }

    static CryptographicException Failure(HelperFailure failure) => new(failure switch {
        HelperFailure.Start => "本地钥匙串组件未启动。",
        HelperFailure.Stdout => "本地钥匙串组件返回无效密钥。",
        HelperFailure.Stderr => "本地钥匙串组件诊断输出超过限额。",
        HelperFailure.Timeout or HelperFailure.Cancelled => "本地钥匙串组件响应超时。",
        HelperFailure.Exit => "钥匙串暂不可用，请解锁后重试。",
        HelperFailure.Cleanup => "本地钥匙串组件未能完成清理。",
        _ => "本地钥匙串组件通信失败。"
    });

    public static byte[] Protect(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope) => Protect(value,scope,MacVaultProcessLimits.Default);
    internal static byte[] Protect(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope, MacVaultProcessLimits limits)
    {
        byte[] key = MasterKey(limits);
        try { return Encrypt(value, scope, key); } finally { CryptographicOperations.ZeroMemory(key); }
    }
    public static byte[] Unprotect(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope) => Unprotect(value,scope,MacVaultProcessLimits.Default);
    internal static byte[] Unprotect(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope, MacVaultProcessLimits limits)
    {
        if (value.Length < Header.Length + 28 || !value[..Header.Length].SequenceEqual(Header)) throw new CryptographicException("凭证格式不属于此 Mac。");
        byte[] key = MasterKey(limits);
        try { return Decrypt(value, scope, key); } finally { CryptographicOperations.ZeroMemory(key); }
    }
    internal static byte[] Encrypt(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope, ReadOnlySpan<byte> key)
    {
        byte[] output = new byte[Header.Length + 28 + value.Length]; Header.CopyTo(output, 0);
        RandomNumberGenerator.Fill(output.AsSpan(Header.Length, 12));
        using var aes = new AesGcm(key, 16);
        aes.Encrypt(output.AsSpan(Header.Length, 12), value, output.AsSpan(Header.Length + 28), output.AsSpan(Header.Length + 12, 16), scope); return output;
    }
    internal static byte[] Decrypt(ReadOnlySpan<byte> value, ReadOnlySpan<byte> scope, ReadOnlySpan<byte> key)
    {
        byte[] plain = new byte[value.Length - Header.Length - 28]; using var aes = new AesGcm(key, 16);
        aes.Decrypt(value.Slice(Header.Length, 12), value[(Header.Length + 28)..], value.Slice(Header.Length + 12, 16), plain, scope); return plain;
    }
}
