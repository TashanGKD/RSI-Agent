using System.Text;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

/// <summary>Validates an export destination without opening live SQLite files.</summary>
public static class MacOutputProtection
{
    public static string Resolve(string destination, string database, string state, string archive, IEnumerable<string>? additionalRoots = null)
    {
        // Preserve the existing source, hardlink and symlink checks first. In
        // particular, do not open/close the active db to compare file identity:
        // closing a second descriptor could release this process's POSIX locks.
        var target = SourcePathProtection.WritablePath(destination);
        var normalized = Canonical(target);
        var activeDatabase = Canonical(database);
        var stateRoot = Canonical(state);
        var protectedFiles = new[] { "", "-wal", "-shm", "-journal", ".health-check.json" }
            .Select(suffix => activeDatabase + suffix)
            .Append(Path.Combine(stateRoot, "settings.json"));
        var protectedRoots = new[] { "keys", "logs", "media", "models" }
            .Select(name => Path.Combine(stateRoot, name))
            .Append(Canonical(archive))
            .Concat((additionalRoots ?? []).Select(root => Canonical(Path.IsPathFullyQualified(root) ? root : Path.Combine(stateRoot, root))));

        if (protectedFiles.Contains(normalized, StringComparer.OrdinalIgnoreCase) || protectedRoots.Any(root => Within(normalized, root)))
            throw new ArgumentException("导出不能覆盖记录库、设置、归档、密钥、日志、媒体或模型，请选择独立输出文件。", nameof(destination));
        if (Directory.Exists(target)) throw new ArgumentException("请选择输出文件，不能替换整个目录。", nameof(destination));
        return target;
    }

    static bool Within(string path, string root) => path.Equals(root, StringComparison.OrdinalIgnoreCase)
        || path.StartsWith(Path.TrimEndingDirectorySeparator(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);

    static string Canonical(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var full = Path.GetFullPath(path);
        if (OperatingSystem.IsMacOS())
        {
            // Only Apple's three standard aliases are normalized. Arbitrary
            // user symlinks are never followed to make an output acceptable.
            foreach (var prefix in new[] { "/var", "/tmp", "/etc" })
                if ((full == prefix || full.StartsWith(prefix + "/", StringComparison.Ordinal))
                    && new DirectoryInfo(prefix).ResolveLinkTarget(true)?.FullName == "/private" + prefix)
                { full = "/private" + full; break; }
            full = full.Normalize(NormalizationForm.FormC);
        }
        return Path.TrimEndingDirectorySeparator(full);
    }
}
