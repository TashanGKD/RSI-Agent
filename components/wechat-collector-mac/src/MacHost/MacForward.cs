using System.Text.Json;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    MacForwardSession? forwardedSession;
    CancellationTokenSource? forwardedCancellation;
    void OpenForwarded(JsonElement command)
    {
        var next = new MacForwardSession(SelectedMessage(command));
        forwardedCancellation?.Cancel(); CancelForwardedFiles(); forwardedSession = next; PublishForwarded();
    }
    void PublishForwarded() { if (forwardedSession is { } current) Post("chat", new { type = "macNative", command = "forwarded", state = current.State() }); }
    Task ForwardedActionAsync(JsonElement command, CancellationToken token)
    {
        var current = forwardedSession ?? throw new ArgumentException("请先打开聊天记录。");
        string session = Text(command, "session"); int revision = Number(command, "revision", -1);
        current.Validate(session, revision);
        switch (Text(command, "operation"))
        {
            case "close":
                forwardedCancellation?.Cancel(); CancelForwardedFiles(); forwardedSession = null;
                Post("chat", new { type = "macNative", command = "closeForwarded" }); return Task.CompletedTask;
            case "back": forwardedCancellation?.Cancel(); CancelForwardedFiles(); current.Back(session, revision); break;
            case "copy":
                Post("chat", new { type = "macNative", command = "clipboard", text = current.CopyText(session, revision) });
                current.SetStatus("聊天记录已复制"); break;
            case "fileReveal": case "fileRetry": case "fileClose": ForwardedFileAction(current, revision, command); break;
            case "item":
                var selection = current.Select(session, revision, Number(command, "item", -1));
                if (selection.kind == "nested") { forwardedCancellation?.Cancel(); CancelForwardedFiles(); break; }
                if (selection.kind == "link")
                {
                    Post("chat", new { type = "macNative", command = "clipboard", text = selection.item.Link!.AbsoluteUri }); current.SetStatus("链接已复制");
                }
                else if (selection.kind == "file") StartForwardedFileSearch(current, revision, selection.itemPath);
                else if (selection.kind == "image")
                {
                    if (account != current.Owner.AccountKey) throw new ArgumentException("当前账号已切换，请重新打开该聊天记录。");
                    forwardedCancellation?.Cancel();
                    var cancellation = forwardedCancellation = OperationCancellation(TimeSpan.FromSeconds(90));
                    current.SetStatus("正在读取本地附件…");
                    _ = TrackShutdownTask(ReadForwardedAttachmentAsync(current, revision, selection, cancellation));
                }
                else current.SetStatus("此转发条目未保存可用的本地预览资源");
                break;
            default: throw new ArgumentException("未知聊天记录操作。");
        }
        PublishForwarded(); return Task.CompletedTask;
    }
    async Task<(string Path, string Mime, string Url)> LoadForwardedImageResourceAsync(WechatUiCollector.WechatDb.WechatDbMessage owner, int[] itemPath, CancellationToken token)
    {
        if (account != owner.AccountKey) throw new ArgumentException("当前账号已切换，请重新打开聊天记录。");
        string selectedArchive = archive;
        var response = await mediaWorkers.ExchangeAsync(new { archive = selectedArchive, action = "forwardedAttachment", account = owner.AccountKey, chat = owner.ConversationUsername, serverId = owner.ServerId.ToString(), itemPath }, token);
        using var result = JsonDocument.Parse(response); var data = result.RootElement;
        if (Text(data, "status") != "ready") throw new ArgumentException(Text(data, "error"));
        var path = MacForwardResources.ValidatePath(Text(data, "path"), [Path.Combine(selectedArchive, "media"), ForwardSourceRoot(owner)]);
        var mime = Text(data, "mime");
        if (mime is not ("image/png" or "image/jpeg" or "image/gif" or "image/webp")) throw new IOException("转发图片格式无效。");
        string id = Guid.NewGuid().ToString("N"); mediaResources[id] = (path, mime);
        if (mediaResources.Count > 256) mediaResources.TryRemove(mediaResources.Keys.First(), out _);
        return (path, mime, "/preview/" + id);
    }
    async Task ReadForwardedAttachmentAsync(MacForwardSession current, int revision, MacForwardSelection selection, CancellationTokenSource cancellation)
    {
        try
        {
            var owner = current.Owner;
            var resource = await LoadForwardedImageResourceAsync(owner, selection.itemPath, cancellation.Token);
            await gate.WaitAsync(cancellation.Token);
            try
            {
                if (!ReferenceEquals(forwardedSession, current) || current.Revision != revision || account != owner.AccountKey || cancellation.IsCancellationRequested) return;
                OpenTrustedSingleImage(owner, resource.Path, resource.Mime, retry => LoadForwardedImageResourceAsync(owner, selection.itemPath, retry));
                current.SetStatus("已打开本地图片"); PublishForwarded();
            }
            finally { gate.Release(); }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            await gate.WaitAsync();
            try
            {
                if (ReferenceEquals(forwardedSession, current) && ReferenceEquals(forwardedCancellation, cancellation) && current.Revision == revision)
                { current.SetStatus("本地转发附件读取超时，请重试。"); PublishForwarded(); }
            }
            finally { gate.Release(); }
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            await gate.WaitAsync();
            try
            {
                if (ReferenceEquals(forwardedSession, current) && current.Revision == revision && !cancellation.IsCancellationRequested)
                {
                    current.SetStatus(error is ArgumentException ? error.Message : "本地转发附件读取未完成，请重试。"); PublishForwarded();
                }
            }
            finally { gate.Release(); }
        }
        finally
        {
            await gate.WaitAsync();
            try { if (ReferenceEquals(forwardedCancellation, cancellation)) forwardedCancellation = null; }
            finally { gate.Release(); cancellation.Dispose(); }
        }
    }
}
