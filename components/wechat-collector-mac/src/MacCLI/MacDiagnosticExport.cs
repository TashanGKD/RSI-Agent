using System.Text.Json;
using WechatCollector.Mac;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.Safety;

internal static class MacDiagnosticExport
{
    public static DiagnosticBundleResult Create(string destination, string settingsPath, string database,
        string archive, AppOptions options, IReadOnlyList<AppLogRecord> logs, IReadOnlyList<string> tail,
        IReadOnlyDictionary<string, object?> health, CancellationToken token)
    {
        var state = Path.GetDirectoryName(Path.GetFullPath(settingsPath))!;
        var protectedPaths = new[] {
            Path.GetFullPath(settingsPath),
            ConfigurationLoader.ResolvePath(options.LogDirectory, state),
            ConfigurationLoader.ResolvePath(options.MediaDirectory, state),
            ConfigurationLoader.ResolvePath(options.JsonlOutputPath, state),
            ConfigurationLoader.ResolvePath(options.AvatarCatalogPath, state),
            Path.Combine(state, "bridge-token"), Path.Combine(state, "bridge-entry.json"),
            Path.Combine(state, "bridge-errors.log"), Path.Combine(state, "profile-ext-credentials.v1.json"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Application Support/LocalWeChatReader")
        };
        string Resolve() => MacOutputProtection.Resolve(destination, database, state, archive, protectedPaths);
        token.ThrowIfCancellationRequested();
        var target = Resolve();
        var parent = Path.GetDirectoryName(target)!;
        ProtectedFileSystem.CreateDirectory(parent);
        var temporary = Path.Combine(parent, ".wechat-diagnostic-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            var cleanHealth = (IReadOnlyDictionary<string, object?>)(LogPrivacy.Value(
                JsonSerializer.SerializeToElement(health), 0, MacDiagnosticsPrivacy.Scrub) ?? new Dictionary<string, object?>());
            var result = DiagnosticBundleBuilder.Create(temporary, options,
                logs.Select(MacDiagnosticsPrivacy.Record).ToArray(), tail.Select(MacDiagnosticsPrivacy.Scrub).ToArray(), cleanHealth);
            token.ThrowIfCancellationRequested();
            target = Resolve();
            ProtectedFileSystem.Move(temporary, target, overwrite: true);
            return new DiagnosticBundleResult(target, result.EntryCount, result.LogRecordCount);
        }
        finally
        {
            if (File.Exists(temporary)) ProtectedFileSystem.Delete(temporary);
        }
    }
}
