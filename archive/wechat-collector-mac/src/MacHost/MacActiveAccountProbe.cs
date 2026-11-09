using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using WechatUiCollector.Diagnostics;

namespace WechatCollector.Mac;

// Reads process/file metadata only. No chat text, keys or screen pixels enter this probe.
public static class MacActiveAccountProbe
{
    const int Limit = 1_048_576;
    const string Executable = "/Applications/WeChat.app/Contents/MacOS/WeChat";
    static readonly Regex Account = new("^wxid_[A-Za-z0-9_]{1,120}$", RegexOptions.CultureInvariant);
    static readonly Regex Database = new("^[A-Za-z0-9_]+\\.db(?:-wal|-shm)?$", RegexOptions.CultureInvariant);
    static readonly HashSet<string> Categories = ["message", "contact", "session", "hardlink", "head_image", "MMKV", "emoticon", "general", "favorite", "chatbot", "bizchat", "sns", "third_app_icon", "solitaire"];

    public static string ParseOpenFileFields(string text, string allowedRoot)
    {
        if (Encoding.UTF8.GetByteCount(text) > Limit || !Path.IsPathFullyQualified(allowedRoot)) throw new InvalidDataException("进程元数据不符合范围。");
        var root = allowedRoot.TrimEnd('/') + "/";
        var accounts = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in text.Split('\0'))
        {
            var field = raw.StartsWith('\n') ? raw[1..] : raw;
            if (!field.StartsWith('n')) continue;
            var path = field[1..];
            if (!path.StartsWith(root, StringComparison.Ordinal)) continue;
            if (path.Any(char.IsControl)) throw new InvalidDataException("进程元数据包含无效文件名。");
            var parts = path[root.Length..].Split('/');
            if (parts.Length == 4 && Account.IsMatch(parts[0]) && parts[1] == "db_storage" && Categories.Contains(parts[2]) && !Database.IsMatch(parts[3]) && parts[3].Length <= 256 && !parts[3].Any(char.IsControl) && parts[3] is not ("." or "..")) continue;
            if (parts.Length != 4 || !Account.IsMatch(parts[0]) || parts[1] != "db_storage" || !Categories.Contains(parts[2]) || !Database.IsMatch(parts[3]))
            {
                // Other normal files are irrelevant; an embedded database path is never evidence.
                if (parts.Any(p => p is "." or "..") || path.Contains("/db_storage/", StringComparison.Ordinal)) throw new InvalidDataException("进程数据库路径不符合范围。");
                continue;
            }
            accounts.Add(parts[0]);
        }
        if (accounts.Count != 1) throw new InvalidDataException("无法唯一确认微信当前账号。");
        return accounts.Single();
    }

    public static async Task<bool> MatchesAsync(int pid, double expectedLaunchTime, string expectedAccount, CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsMacOS() || pid <= 0 || !double.IsFinite(expectedLaunchTime) || expectedLaunchTime <= 0 || !Account.IsMatch(expectedAccount)) return Rejected("invalid_binding_inputs");
        try
        {
            var identity = Identity(pid);
            double launchDelta = new DateTimeOffset(new DateTime(identity.Started,DateTimeKind.Utc)).ToUnixTimeMilliseconds()/1000.0-expectedLaunchTime;
            if (Math.Abs(launchDelta) > .001) return Rejected("launch_time_mismatch",launchDelta*1000);
            var start = new ProcessStartInfo("/usr/sbin/lsof") { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var argument in new[] { "-nP", "-p", pid.ToString(System.Globalization.CultureInfo.InvariantCulture), "-F0n" }) start.ArgumentList.Add(argument);
            using var process = Process.Start(start) ?? throw new IOException("无法读取进程元数据。");
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            deadline.CancelAfter(TimeSpan.FromSeconds(5));
            using var stop = deadline.Token.Register(() => KillOwned(process));
            var errors = DrainAsync(process.StandardError, deadline.Token);
            string text;
            try
            {
                text = await ReadBoundedAsync(process.StandardOutput, deadline.Token);
                await process.WaitForExitAsync(deadline.Token);
                await errors;
            }
            finally
            {
                deadline.Cancel();
                KillOwned(process);
                try { await errors; } catch (OperationCanceledException) { }
                using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                try { await process.WaitForExitAsync(cleanup.Token); } catch (OperationCanceledException) { }
            }
            if (process.ExitCode != 0 || identity != Identity(pid)) return Rejected("process_metadata_changed");
            var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files");
            var account = ParseOpenFileFields(text, root);
            var accountDirectory = Path.Combine(root, account);
            if ((File.GetAttributes(accountDirectory) & FileAttributes.ReparsePoint) != 0 || (File.GetAttributes(Path.Combine(accountDirectory, "db_storage")) & FileAttributes.ReparsePoint) != 0) return Rejected("linked_account_directory");
            return StringComparer.Ordinal.Equals(account, expectedAccount) || Rejected("selected_account_mismatch");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { return Rejected("metadata_timeout"); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidOperationException or System.ComponentModel.Win32Exception or ArgumentException) { return Rejected("metadata_"+error.GetType().Name); }
    }
    static bool Rejected(string reason,double? launchDeltaMilliseconds=null)
    {
        RuntimeEventSource.Emit(AppLogLevel.Warning,"MAC_WINDOW_ACCOUNT_BINDING_FAILED","MacActiveAccountProbe","微信窗口账号身份尚未对应。",new Dictionary<string,object?>{["reason"]=reason,["launchDeltaMilliseconds"]=launchDeltaMilliseconds});
        return false;
    }
    static (string Path, long Started) Identity(int pid)
    {
        var bytes = new byte[4096];
        int length = proc_pidpath(pid, bytes, (uint)bytes.Length);
        if (length <= 0) throw new InvalidDataException("无法确认微信进程。");
        var path = Encoding.UTF8.GetString(bytes, 0, Array.IndexOf(bytes, (byte)0) is var end && end >= 0 ? end : length);
        if (path != Executable) throw new InvalidDataException("窗口不属于指定微信应用。");
        using var process = Process.GetProcessById(pid);
        return (path, process.StartTime.ToUniversalTime().Ticks);
    }
    static async Task<string> ReadBoundedAsync(StreamReader reader, CancellationToken token)
    {
        var result = new StringBuilder(); var buffer = new char[4096]; int count;
        while ((count = await reader.ReadAsync(buffer.AsMemory(), token)) > 0)
        {
            result.Append(buffer, 0, count);
            if (result.Length > Limit || Encoding.UTF8.GetByteCount(result.ToString()) > Limit) throw new InvalidDataException("进程元数据过大。");
        }
        return result.ToString();
    }
    static async Task DrainAsync(StreamReader reader, CancellationToken token)
    { var buffer = new char[1024]; while (await reader.ReadAsync(buffer.AsMemory(), token) > 0) { } }
    static void KillOwned(Process process)
    { try { if (!process.HasExited) process.Kill(); } catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception) { } }
    [DllImport("/usr/lib/libproc.dylib")] static extern int proc_pidpath(int pid, byte[] buffer, uint bufferSize);
}
