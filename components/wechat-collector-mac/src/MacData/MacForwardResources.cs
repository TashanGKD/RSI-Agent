namespace WechatCollector.Mac;

public static class MacForwardResources
{
    // Read boundaries are checked independently of the worker response. No source
    // file is opened until every component below the allowed root rejects links.
    public static string ValidatePath(string path, IReadOnlyList<string> allowedRoots) => Validate(path, allowedRoots, 128L * 1024 * 1024);
    public static string ValidateFilePath(string path, IReadOnlyList<string> allowedRoots) => Validate(path, allowedRoots, null);
    static string Validate(string path, IReadOnlyList<string> allowedRoots, long? maximumBytes)
    {
        if (!Path.IsPathFullyQualified(path)) throw new IOException("转发附件位置无法验证。");
        path = Path.GetFullPath(path);
        foreach (var rootPath in allowedRoots)
        {
            var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(rootPath));
            if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal)) continue;
            for (string? current = path; current is not null; current = current == root ? null : Path.GetDirectoryName(current))
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("转发附件位置不能是链接。");
            }
            if (!File.Exists(path) || maximumBytes.HasValue && new FileInfo(path).Length > maximumBytes.Value) throw new IOException("转发附件不存在或过大。");
            return path;
        }
        throw new IOException("转发附件位置不属于当前账号。");
    }
}
