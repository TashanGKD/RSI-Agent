using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using WechatUiCollector.Storage;

namespace WechatUiCollector.WechatDb;

// Platform implementations run inside the services' existing lease/backup scope.
// They must not acquire that lease again or create a second full backup.
public interface IWechatLocalImportProvider
{
    string ResolveAccountRoot(string? accountRoot, string? filesRoot = null);
    string? ResolveAccountRootForAccount(string account, string? accountRoot = null)
    {
        var root = ResolveAccountRoot(accountRoot);
        return string.Equals(Path.GetFileName(root), account, StringComparison.Ordinal) ? root : null;
    }
    Task<WechatDbMessageImportResult> ImportMessagesAsync(SqliteMessageStore store, string? accountRoot, string? filesRoot, IProgress<string>? progress, CancellationToken token, bool full);
    Task<WechatContactImportResult> ImportContactsAsync(SqliteMessageStore store, string? accountRoot, IProgress<string>? progress, CancellationToken token, bool full);
}

public static class WechatLocalImportProviders
{
    private static IWechatLocalImportProvider? provider;
    public static IWechatLocalImportProvider? Current => Volatile.Read(ref provider);
    public static void Register(IWechatLocalImportProvider value)
    {
        ArgumentNullException.ThrowIfNull(value);
        var previous = Interlocked.CompareExchange(ref provider, value, null);
        if (previous is not null && !ReferenceEquals(previous, value)) throw new InvalidOperationException("Local import provider is already registered.");
    }
}
