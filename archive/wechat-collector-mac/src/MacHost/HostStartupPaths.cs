using WechatUiCollector.Configuration;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

/// Resolve saved startup selections before creating or opening any writable data.
/// A missing settings file uses Mac defaults; invalid saved settings fail closed.
public sealed record HostStartupPaths(string StateDirectory, string DatabasePath, int BackupRetentionCount, string ArchivePath)
{
    public static HostStartupPaths Resolve(string stateDirectory, string legacyArchive)
    {
        legacyArchive = Path.GetFullPath(legacyArchive);
        SourcePathProtection.ProtectDirectory(legacyArchive);
        stateDirectory = SourcePathProtection.WritablePath(stateDirectory);
        var settingsFile = SourcePathProtection.WritablePath(Path.Combine(stateDirectory, "settings.json"));
        var options = File.Exists(settingsFile) ? ConfigurationLoader.LoadOptions(settingsFile) : null;
        var configuredDatabase = options?.DatabasePath ?? Path.Combine(stateDirectory, "records.db");
        // Do not turn an explicitly empty/null saved path into an unrelated DB.
        if (options is not null) ArgumentException.ThrowIfNullOrWhiteSpace(options.DatabasePath);
        var database = SourcePathProtection.DatabasePath(ConfigurationLoader.ResolvePath(configuredDatabase, stateDirectory));
        var independentArchive = SourcePathProtection.WritablePath(Path.Combine(stateDirectory, "archive"));
        if (database.Equals(independentArchive, StringComparison.OrdinalIgnoreCase) || database.StartsWith(independentArchive + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("记录库不能放在本地读取归档目录内，请选择独立的记录保存位置。");
        var independentIndex = Path.Combine(independentArchive, "index.db");
        var archive = legacyArchive;
        if (File.Exists(independentIndex))
        {
            // This index will be writable during a subsequent sync. Reject links
            // and protected sources now instead of silently choosing an older copy.
            SourcePathProtection.DatabasePath(independentIndex);
            archive = independentArchive;
        }
        return new(stateDirectory, database, options?.BackupRetentionCount ?? 2, archive);
    }
}
