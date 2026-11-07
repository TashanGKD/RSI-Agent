using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// The original ForwardedRecordWindow's row/actions/history, without WPF types.
public sealed class MacForwardSession
{
    sealed record Frame(string Title, WechatForwardedRecord Record, int[] Path, int ScrollIndex);
    readonly Stack<Frame> history = new();
    Frame current;
    readonly string session = Guid.NewGuid().ToString("N");
    int revision = 1;
    string status = "";
    object? fileCandidates;
    public WechatDbMessage Owner { get; }
    public int Revision => revision;
    public MacForwardSession(WechatDbMessage owner)
    {
        Owner = owner;
        var card = WechatDbCard.Read(owner);
        current = new(card.Title ?? "聊天记录", card.Forwarded ?? throw new ArgumentException("此消息没有已保存的聊天记录。"), [], 0);
    }
    public void Validate(string expectedSession, int expectedRevision)
    {
        if (expectedSession != session || expectedRevision != revision) throw new ArgumentException("聊天记录窗口已更新，请重新选择条目。");
    }
    public MacForwardSelection Select(string expectedSession, int expectedRevision, int index)
    {
        Validate(expectedSession, expectedRevision);
        if (index < 0 || index >= current.Record.Items.Count) throw new ArgumentException("转发条目已更新，请重新选择。");
        var item = current.Record.Items[index];
        var path = current.Path.Append(index).ToArray();
        if (item.Nested is { } nested)
        {
            history.Push(current with { ScrollIndex = index }); current = new(item.Text, nested, path, 0); revision++; status = "";
            return new("nested", item, path);
        }
        return new(item.FileName is not null ? "file" : item.ImageHash is not null ? "image" : item.Link is not null ? "link" : "none", item, path);
    }
    public void Back(string expectedSession, int expectedRevision)
    {
        Validate(expectedSession, expectedRevision);
        if (history.TryPop(out var previous)) { current = previous; revision++; status = ""; }
    }
    public string CopyText(string expectedSession, int expectedRevision)
    {
        Validate(expectedSession, expectedRevision);
        return current.Title + "\n" + current.Record.ReadableText();
    }
    public void SetStatus(string value) => status = value;
    public void SetFileCandidates(object? value) => fileCandidates = value;
    public object State() => new
    {
        type = "forwarded", session, revision, title = current.Title,
        summary = $"{current.Record.Items.Count} 条消息" + (current.Record.Status is { } detail ? " · " + detail : ""),
        canBack = history.Count > 0, scrollIndex = current.ScrollIndex, status, fileCandidates,
        items = current.Record.Items.Select((item, index) => new
        {
            index, heading = item.Heading, text = item.Text, quote = item.Quote,
            detail = item.Type == 1 ? "" : item.Detail + (item.Type is 3 or 4 or 37 ? " · 转发内媒体暂不支持播放" : ""),
            action = item.Nested is not null ? "查看聊天记录 →" : item.ImageHash is not null ? "查看本地图片" : item.Link is not null ? "复制链接" : "查找本地文件",
            hasAction = item.Nested is not null || item.FileName is not null || item.ImageHash is not null || item.Link is not null
        }).ToArray()
    };
}

public sealed record MacForwardSelection(string kind, WechatForwardedItem item, int[] itemPath);
