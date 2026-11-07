using WechatUiCollector.Collection;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// FileLocationWindow's bounded same-name search and explicit verification flow.
// Paths remain server-side; a returned token/index never grants path authority.
public sealed class MacForwardFiles
{
    readonly WechatForwardedItem item;
    readonly string root;
    AttachmentSourceCandidate[] candidates = [];
    string status = "正在查找本地文件…";
    bool busy = true;
    public string Token { get; } = Guid.NewGuid().ToString("N");
    public WechatDbMessage Owner { get; }
    public int[] ItemPath { get; }
    public MacForwardFiles(WechatDbMessage owner, int[] itemPath, string sourceRoot)
    {
        if (itemPath.Length is < 1 or > 5) throw new ArgumentException("转发文件条目标识无效。");
        Owner = owner; ItemPath = itemPath.ToArray(); root = Path.GetFullPath(sourceRoot);
        var record = WechatDbCard.Read(owner).Forwarded ?? throw new ArgumentException("父消息没有已保存的聊天记录。");
        WechatForwardedItem? selected = null;
        for (int depth = 0; depth < itemPath.Length; depth++)
        {
            int index = itemPath[depth];
            if (index < 0 || index >= record.Items.Count) throw new ArgumentException("转发文件条目已过期。");
            selected = record.Items[index];
            if (depth + 1 < itemPath.Length) record = selected.Nested ?? throw new ArgumentException("此条目没有子聊天记录。");
        }
        item = selected!;
        if (item.FileName is null) throw new ArgumentException("此转发条目没有可查找的文件名。");
    }
    public async Task SearchAsync(CancellationToken token)
    {
        var found = await Task.Run(() =>
        {
            ValidateDirectory(root);
            var files = Path.Combine(root, "msg", "file");
            if (!Directory.Exists(files)) return Array.Empty<AttachmentSourceCandidate>();
            ValidateDirectory(files);
            using var search = new AttachmentSourceCandidateService(root, searchSubdirectories: true);
            return search.FindCandidates(item.FileName, Path.GetExtension(item.FileName), item.FileSize, null, null).Candidates.Where(c => c.NameMatches).ToArray();
        }, token);
        token.ThrowIfCancellationRequested(); candidates = found;
        status = found.Length == 0 ? "当前搜索范围内未找到同名文件。下载或恢复文件后，可重新查找。" : $"找到 {found.Length} 个同名文件，请选择。" + (item.FileHash is null ? " 尚无法确认是否为原附件。" : "");
        busy = false;
    }
    void ValidateDirectory(string path)
    {
        for (string? current = Path.GetFullPath(path); current is not null; current = current == root ? null : Path.GetDirectoryName(current))
        {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("本地文件目录不能是链接。");
        }
    }
    public async Task<string> VerifyAsync(string token, int index, CancellationToken cancellation)
    {
        if (token != Token || index < 0 || index >= candidates.Length) throw new ArgumentException("文件候选已过期，请重新查找并选择。");
        var selected = MacForwardResources.ValidateFilePath(candidates[index].FullPath, [root]);
        if (!await WechatFileVerification.MatchesAsync(selected, item.FileSize, item.FileHash, cancellation)) throw new ArgumentException("与原附件不一致，请选择其他文件或重新查找。");
        cancellation.ThrowIfCancellationRequested();
        return MacForwardResources.ValidateFilePath(selected, [root]);
    }
    public string RevealedStatus => item.FileHash is null ? "已打开文件夹；尚无法确认是否为原附件。" : "与原附件一致，已打开文件夹。";
    public void SetStatus(string value, bool isBusy = false) { status = value; busy = isBusy; }
    public object State() => new
    {
        token = Token, title = item.FileName, status, busy,
        items = candidates.Select((candidate, index) => new
        {
            index, directory = Path.GetDirectoryName(candidate.FullPath) ?? "",
            summary = Size(candidate.ByteSize) + " · " + (!item.FileSize.HasValue ? "原大小未知" : candidate.SizeMatches ? "大小一致" : "大小不一致"),
            details = $"{candidate.ByteSize:N0} 字节 · 修改时间 {candidate.LastWriteTimeUtc.ToLocalTime():yyyy-MM-dd HH:mm}\n" + (item.FileHash is null ? "原消息缺少校验信息，无法确认是否为原附件。" : "打开文件夹前，将与原消息中的文件摘要核对。")
        }).ToArray()
    };
    static string Size(long value) => value >= 1024L * 1024 * 1024 ? $"{value / (1024.0 * 1024 * 1024):0.#} GB" : value >= 1024 * 1024 ? $"{value / (1024.0 * 1024):0.#} MB" : value >= 1024 ? $"{value / 1024.0:0.#} KB" : $"{value} B";
}
