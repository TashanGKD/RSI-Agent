using System.Text.RegularExpressions;
using WechatUiCollector.Collection;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// Shared read-only FileLocationWindow model. Only server-issued candidate indices
// grant authority; a filename is metadata, never a path supplied by the web UI.
public sealed class MacFileLocation
{
    readonly string root, name;
    readonly long? size;
    readonly string? hash;
    readonly DateTimeOffset? time;
    AttachmentSourceCandidate[] candidates = [];
    string status = "正在查找本地文件…";
    bool busy = true;
    public string Token { get; private set; } = Guid.NewGuid().ToString("N");
    public MacFileLocation(string sourceRoot, string fileName, long? expectedSize, string? expectedHash, DateTimeOffset? observedAt)
    {
        root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(sourceRoot));
        if (string.IsNullOrWhiteSpace(fileName) || fileName.Length > 1024 || fileName.IndexOfAny(['/', '\\', '\0']) >= 0 || fileName is "." or "..") throw new ArgumentException("原消息的文件名无效。");
        name = fileName; size = expectedSize; hash = expectedHash; time = observedAt;
    }
    void DirectoryBoundary(string directory)
    {
        for (string? current = directory; current is not null; current = Path.GetDirectoryName(current))
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("附件目录不能是链接。");
    }
    public async Task SearchAsync(CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); Token = Guid.NewGuid().ToString("N"); candidates = []; busy = true;
        var found = await Task.Run(() =>
        {
            DirectoryBoundary(root);
            var files = Path.Combine(root, "msg", "file");
            if (!Directory.Exists(files)) return Array.Empty<AttachmentSourceCandidate>();
            DirectoryBoundary(files);
            var options = new EnumerationOptions { RecurseSubdirectories = false, IgnoreInaccessible = false, AttributesToSkip = FileAttributes.ReparsePoint };
            // Same source scope, stability delay, ranking, 20k inspection and 20
            // candidate budgets as the original AttachmentSourceCandidateService.
            var months = Directory.EnumerateDirectories(files, "*", options).Take(20000).Where(p => Regex.IsMatch(Path.GetFileName(p), @"^\d{4}-\d{2}$")).OrderByDescending(p => p, StringComparer.Ordinal).Take(20000).Append(files);
            var matches = new List<AttachmentSourceCandidate>(); int inspected = 0;
            var suffix = new Regex("^" + Regex.Escape(Path.GetFileNameWithoutExtension(name)) + @" ?\((?:[2-9]|[1-9][0-9]+)\)" + Regex.Escape(Path.GetExtension(name)) + "$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            foreach (var month in months)
            {
                token.ThrowIfCancellationRequested(); DirectoryBoundary(month);
                foreach (var path in Directory.EnumerateFiles(month, "*", options))
                {
                    token.ThrowIfCancellationRequested(); if (++inspected > 20000) break;
                    var info = MacFileLocationRead.RegularInfo(path);
                    if (info is null || DateTime.UtcNow - info.Value.LastWriteTimeUtc < TimeSpan.FromSeconds(1)) continue;
                    var foundName = Path.GetFileName(path);
                    if (!foundName.Equals(name, StringComparison.OrdinalIgnoreCase) && !suffix.IsMatch(foundName)) continue;
                    bool sameSize = size.HasValue && size.Value == info.Value.Size;
                    bool sameTime = time.HasValue && Math.Abs((info.Value.LastWriteTimeUtc - time.Value.UtcDateTime).TotalMinutes) <= 5;
                    matches.Add(new AttachmentSourceCandidate(path, foundName, info.Value.Size, info.Value.LastWriteTimeUtc, 110 + (sameSize ? 40 : 0) + (sameTime ? 30 : 0), true, sameSize, sameTime));
                }
                if (inspected >= 20000) break;
            }
            return matches.OrderByDescending(c => c.Score).ThenByDescending(c => c.LastWriteTimeUtc).Take(20).ToArray();
        }, token);
        token.ThrowIfCancellationRequested(); candidates = found; busy = false;
        status = found.Length == 0 ? "当前搜索范围内未找到同名文件。下载或恢复文件后，可重新查找。" : $"找到 {found.Length} 个同名文件，请选择。" + (hash is null ? " 尚无法确认是否为原附件。" : "");
    }
    public async Task<string> VerifyAsync(string token, int index, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (token != Token || index < 0 || index >= candidates.Length) throw new ArgumentException("文件候选已过期，请重新查找并选择。");
        DirectoryBoundary(root);
        var selected = MacForwardResources.ValidateFilePath(candidates[index].FullPath, [root]);
        using var input = MacFileLocationRead.Open(selected);
        if (!await WechatFileVerification.MatchesAsync(input.Stream, size, hash, cancellation)) throw new ArgumentException("与原附件不一致，请选择其他文件或重新查找。");
        cancellation.ThrowIfCancellationRequested(); input.EnsureCurrent(selected); DirectoryBoundary(root);
        return MacForwardResources.ValidateFilePath(selected, [root]);
    }
    public string RevealedStatus => hash is null ? "已打开文件夹；尚无法确认是否为原附件。" : "与原附件一致，已打开文件夹。";
    public void SetStatus(string value, bool isBusy = false) { status = value; busy = isBusy; }
    public object State() => new { token = Token, title = name, status, busy, items = candidates.Select((c, index) => new
    {
        index, name = c.Name, path = c.FullPath, directory = Path.GetDirectoryName(c.FullPath),
        summary = Size(c.ByteSize) + " · " + (!size.HasValue ? "原大小未知" : c.SizeMatches ? "大小一致" : "大小不一致"),
        details = $"{c.FullPath}\n{c.ByteSize:N0} 字节 · 修改时间 {c.LastWriteTimeUtc.ToLocalTime():yyyy-MM-dd HH:mm}\n" + (hash is null ? "原消息缺少校验信息，无法确认是否为原附件。" : "打开文件夹前，将与原消息中的文件摘要核对。")
    }).ToArray() };
    static string Size(long value) => value >= 1073741824 ? $"{value / 1073741824.0:0.#} GB" : value >= 1048576 ? $"{value / 1048576.0:0.#} MB" : value >= 1024 ? $"{value / 1024.0:0.#} KB" : $"{value} B";
}
