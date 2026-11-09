using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

public sealed record MacSetupSource(string Path, string Name);
public static class MacSetupSources
{
    public static string Folder(string path)
    {
        if (!System.IO.Path.IsPathFullyQualified(path)) throw new ArgumentException("请选择完整的目录位置。");
        path = System.IO.Path.TrimEndingDirectorySeparator(System.IO.Path.GetFullPath(path));
        for (string? current = path; current is not null; current = System.IO.Path.GetDirectoryName(current))
        {
            var attributes = File.GetAttributes(current);
            if ((attributes & FileAttributes.ReparsePoint) == 0) continue;
            if (current is "/var" or "/tmp" or "/etc" && new DirectoryInfo(current).ResolveLinkTarget(true)?.FullName == "/private" + current) continue;
            throw new IOException("所选目录不能包含链接。");
        }
        if (!Directory.Exists(path)) throw new ArgumentException("所选目录不存在。");
        return path;
    }
    public static MacSetupSource[] Discover(string selected, string state, string archive)
    {
        if (!Directory.Exists(selected)) return [];
        var root = Folder(selected);
        var home = System.IO.Path.TrimEndingDirectorySeparator(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
        if (root == home || root == System.IO.Path.GetPathRoot(root)) throw new ArgumentException("请选择 xwechat_files 文件夹或其中的账号文件夹，不扫描个人目录。");
        using var provider = new MacImportProvider(state, archive, root);
        if (Directory.Exists(System.IO.Path.Combine(root, "db_storage")))
        {
            string account = provider.ResolveAccountRoot(root);
            return [new(account, System.IO.Path.GetFileName(account))];
        }
        var children = Directory.EnumerateDirectories(root).Take(257).ToArray();
        if (children.Length > 256) throw new ArgumentException("所选位置目录过多，请直接选择微信账号文件夹。");
        var result = new List<MacSetupSource>();
        foreach (var child in children)
        {
            try
            {
                Folder(child);
                if (!Directory.Exists(System.IO.Path.Combine(child, "db_storage"))) continue;
                string account = provider.ResolveAccountRoot(child);
                result.Add(new(account, System.IO.Path.GetFileName(account)));
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException) { }
        }
        return result.OrderBy(item => item.Name, StringComparer.Ordinal).ToArray();
    }
    public static bool CachedCredentialsExist(string archive, string state, string account)
    {
        var independent = System.IO.Path.Combine(state, "archive");
        var selected = File.Exists(System.IO.Path.Combine(independent, "index.db")) ? independent : archive;
        try
        {
            Folder(System.IO.Path.Combine(selected, "keys"));
            string path = System.IO.Path.Combine(selected, "keys", account + ".keys.json");
            return File.Exists(path) && (File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) == 0 && new FileInfo(path).Length > 0;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException) { return false; }
    }
}
