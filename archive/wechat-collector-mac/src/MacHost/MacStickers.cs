using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;
using WechatUiCollector.Safety;
using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    // Synthetic tests replace only the trusted loader; no UI supplied URL/path
    // or hash is admitted by the sticker action.
    internal Func<SqliteMessageStore, MacStickerLoader>? stickerLoaderFactory;
    readonly object stickerLoaderLock = new();
    MacStickerLoader? stickerLoader;
    SqliteMessageStore? stickerLoaderStore, stickerRequestedStore;
    CancellationTokenSource? stickerCancellation;
    int stickerRequestedVersion;
    string stickerRequestedAccount = "", stickerRequestedChat = "";
    readonly ConcurrentDictionary<string, (string Path, string Mime, byte[] Digest)> stickerResources = new();

    MacStickerLoader Stickers(SqliteMessageStore activeStore)
    {
        lock (stickerLoaderLock)
        {
            if (!ReferenceEquals(stickerLoaderStore, activeStore))
            {
                stickerLoaderStore = activeStore;
                stickerLoader = stickerLoaderFactory?.Invoke(activeStore) ?? new MacStickerLoader(activeStore.AssetDirectory, async (message, ct) =>
                {
                    var resource = await LoadMediaAsync(message, ct);
                    if (!resource.Mime.StartsWith("image/", StringComparison.Ordinal) || new FileInfo(resource.Path).Length > 8388608) return null;
                    return ReadStickerBytes(resource.Path, ct, ownedCache: false);
                }, (bytes, ct) => MacStickerProbe.InspectAsync(bytes, ct));
            }
            return stickerLoader!;
        }
    }
    string StickerResource(string path, string mime, byte[] verifiedBytes)
    {
        var digest = SHA256.HashData(verifiedBytes);
        var id = Guid.NewGuid().ToString("N"); stickerResources[id] = (path, mime, digest); mediaResources[id] = (path, mime);
        while (stickerResources.Count > 128)
        {
            var oldest = stickerResources.Keys.First(); stickerResources.TryRemove(oldest, out _); mediaResources.TryRemove(oldest, out _);
        }
        if (mediaResources.Count > 256) mediaResources.TryRemove(mediaResources.Keys.First(), out _);
        return "/preview/" + id;
    }
    // Keep only fingerprints in the resource registry. Serve verified bytes,
    // rather than reopening a mutable cache path later through Results.File.
    public bool IsStickerResource(string id) => stickerResources.ContainsKey(id);
    public (byte[] Bytes, string Mime)? ReadStickerResource(string id)
    {
        if (!stickerResources.TryGetValue(id, out var resource)) return null;
        try
        {
            var bytes = ReadStickerBytes(resource.Path, LifetimeToken);
            return SHA256.HashData(bytes).SequenceEqual(resource.Digest) ? (bytes, resource.Mime) : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException or OperationCanceledException) { return null; }
    }
    static byte[] ReadStickerBytes(string path, CancellationToken token, bool ownedCache = true)
    {
        // Source archives remain write protected. The worker-bound local path
        // needs a read boundary; writable-path checks apply only to app caches.
        if (ownedCache) SourcePathProtection.WritablePath(path);
        MacMediaAccess.ValidateFile(path, [Path.GetDirectoryName(path)!]);
        using var input = File.OpenRead(path); using var output = new MemoryStream(); var buffer = new byte[16384];
        if (input.Length is < 1 or > 8388608) throw new IOException("表情资源超出限制。");
        int count;
        while ((count = input.Read(buffer)) > 0)
        {
            token.ThrowIfCancellationRequested();
            if (output.Length + count > 8388608) throw new IOException("表情资源超出限制。");
            output.Write(buffer, 0, count);
        }
        if (ownedCache) SourcePathProtection.WritablePath(path);
        MacMediaAccess.ValidateFile(path, [Path.GetDirectoryName(path)!]);
        if (output.Length == 0) throw new IOException("表情资源为空。");
        return output.ToArray();
    }
    async Task<(string? Url, string Status)> LoadStickerThumbnailAsync(WechatDbMessage message, SqliteMessageStore activeStore, CancellationToken token)
    {
        var sticker = await Stickers(activeStore).LoadAsync(message, allowDownload: false, token);
        return sticker is null ? (null, "未找到已保存表情 · 点击可尝试下载") : (StickerResource(sticker.ThumbnailPath, "image/png", sticker.Image.ThumbnailPng), "已保存表情 · 点击预览");
    }
    void CancelObsoleteSticker()
    {
        if (stickerCancellation is { } pending && (stickerRequestedVersion != version || stickerRequestedAccount != account || stickerRequestedChat != chat || !ReferenceEquals(stickerRequestedStore, store))) TryCancel(pending);
    }
    void StartSticker(WechatDbMessage message, int requestedVersion, int index)
    {
        if (message.Type != WechatDbMessageType.Emoji || message.AccountKey != account || message.ConversationUsername != chat) throw new ArgumentException("表情所属账号或会话已变化，请重新选择。");
        if (stickerCancellation is { } previous) TryCancel(previous);
        var cancellation = stickerCancellation = OperationCancellation();
        var activeStore = store; var selectedAccount = account; var selectedChat = chat;
        stickerRequestedVersion = requestedVersion; stickerRequestedAccount = selectedAccount; stickerRequestedChat = selectedChat; stickerRequestedStore = activeStore;
        var loader = Stickers(activeStore);
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                var result = await loader.LoadAsync(message, allowDownload: true, cancellation.Token) ?? throw new IOException("没有可验证的本地表情。");
                await gate.WaitAsync(cancellation.Token);
                try
                {
                    if (!CurrentStickerAttempt()) return;
                    Post("chat", new { type = "thumbnail", version = requestedVersion, index, data = StickerResource(result.ThumbnailPath, "image/png", result.Image.ThumbnailPng), status = "已保存表情 · 点击预览" });
                    OpenTrustedImageCore(message, result.Path, result.Image.Mime, async ct =>
                    {
                        if (!ReferenceEquals(store, activeStore) || account != selectedAccount || chat != selectedChat) throw new ArgumentException("表情所属账号或记录库已变化，请重新打开。");
                        await using var reader = new LocalRecordReader(activeStore.DatabasePath); await reader.OpenAsync(ct);
                        var current = await reader.MessageAsync(new RecordIdentity(message.AccountKey, message.ConversationUsername, message.ServerId.ToString(System.Globalization.CultureInfo.InvariantCulture)), ct);
                        if (current.Type != WechatDbMessageType.Emoji || WechatDbCard.Read(current).EmojiHash != WechatDbCard.Read(message).EmojiHash) throw new ArgumentException("表情消息已变化，请重新打开。");
                        var cached = await loader.LoadAsync(current, allowDownload: false, ct) ?? throw new IOException("本地表情已不可用。");
                        return (cached.Path, cached.Image.Mime, StickerResource(cached.Path, cached.Image.Mime, cached.Bytes));
                    }, kind: "sticker", trustedBytes: result.Bytes);
                }
                finally { gate.Release(); }
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
            catch (Exception error) when (error is not OutOfMemoryException)
            {
                await gate.WaitAsync();
                try { if (CurrentStickerAttempt()) Post("chat", new { type = "feedback", version = requestedVersion, index, text = "表情暂不可用：资源可能过期或格式不支持" }); }
                finally { gate.Release(); }
            }
            finally { Interlocked.CompareExchange(ref stickerCancellation, null, cancellation); cancellation.Dispose(); }

            bool CurrentStickerAttempt() => !cancellation.IsCancellationRequested && ReferenceEquals(stickerCancellation, cancellation) && ReferenceEquals(store, activeStore) && account == selectedAccount && chat == selectedChat && version == requestedVersion && index >= 0 && index < messages.Count && messages[index].AccountKey == message.AccountKey && messages[index].ConversationUsername == message.ConversationUsername && messages[index].ServerId == message.ServerId && WechatDbCard.Read(messages[index]).EmojiHash == WechatDbCard.Read(message).EmojiHash;
        }));
    }
}
