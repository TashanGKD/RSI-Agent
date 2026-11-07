using System;
using System.IO;
using WechatUiCollector.Configuration;

namespace WechatUiCollector.Cli;

/// Mac CLI shares the desktop's saved settings and database selection.
/// Optional directories make path resolution testable without changing HOME.
public static class MacCliStartup
{
    public static string? ResolveRuntimeProject(string binaryDirectory, string? configured)
    {
        if (configured is not null)
        {
            if (!Path.IsPathFullyQualified(configured) || configured.Contains('\0'))
                throw new ArgumentException("本地读取组件目录必须为绝对路径。");
            return Path.GetFullPath(configured);
        }
        var binaries = Path.TrimEndingDirectorySeparator(Path.GetFullPath(binaryDirectory));
        var resources = Path.GetDirectoryName(binaries);
        if (Path.GetFileName(binaries) != "cli" || resources is null || Path.GetFileName(resources) != "Resources"
            || Path.GetFileName(Path.GetDirectoryName(resources)) != "Contents") return null;
        var project = Path.Combine(resources, "Project");
        if (!Directory.Exists(Path.Combine(project, "reference-web")))
            throw new IOException("应用的本地读取组件不完整，请使用完整的微信记录应用。");
        return project;
    }

    public static string? InheritWorkerSettings(string? requested, string? inherited)
    {
        if (requested is not null || inherited is null) return requested;
        if (!Path.IsPathFullyQualified(inherited) || inherited.Contains('\0') || inherited.Length > 32768)
            throw new ArgumentException("后台任务配置路径必须为绝对路径。");
        return Path.GetFullPath(inherited);
    }
    public static string ResolveSettings(string? requested, string? stateDirectory = null, string? workingDirectory = null)
    {
        var cwd = workingDirectory ?? Environment.CurrentDirectory;
        if (requested is not null) return Path.GetFullPath(requested, cwd);
        var state = stateDirectory ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Library/Application Support/WechatCollectorMac");
        // An absent desktop settings file is still the selected settings path.
        // Never discover a different account/configuration from the caller's CWD.
        return Path.GetFullPath(Path.Combine(state, "settings.json"), cwd);
    }

    public static AppOptions LoadOptions(string settingsPath)
        => File.Exists(settingsPath) ? ConfigurationLoader.LoadOptions(settingsPath)
            : new AppOptions { DatabasePath = "records.db" };

    public static string ResolveDatabase(CliInvocation invocation, string? stateDirectory = null, string? workingDirectory = null)
    {
        var cwd = workingDirectory ?? Environment.CurrentDirectory;
        if (invocation.Database is not null) return Path.GetFullPath(invocation.Database, cwd);
        var settings = ResolveSettings(invocation.Settings, stateDirectory, cwd);
        var options = LoadOptions(settings);
        ArgumentException.ThrowIfNullOrWhiteSpace(options.DatabasePath);
        return ConfigurationLoader.ResolvePath(options.DatabasePath, Path.GetDirectoryName(settings));
    }
}
