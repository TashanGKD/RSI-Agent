using System.Diagnostics;
using System.Collections.Concurrent;
using System.Text.Json;
using WechatUiCollector.WechatDb;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    readonly ConcurrentDictionary<string, (string Path, string Mime)> mediaResources = new();
    readonly SemaphoreSlim thumbnailGate = new(2);
    readonly MacWorkerPool mediaWorkers = new();
    // Explicit reads must not spend their timeout waiting for viewport previews.
    readonly MacWorkerPool foregroundMediaWorkers = new(1);
    public void StopMediaWorkers() { foreach (var job in thumbnailJobs.Values) TryCancel(job); if (stickerCancellation is { } sticker) TryCancel(sticker); mediaWorkers.Dispose(); foregroundMediaWorkers.Dispose(); }
    readonly ConcurrentDictionary<(int Version, int Index), CancellationTokenSource> thumbnailJobs = new();
    void CancelThumbnail(JsonElement command)
    {
        if (thumbnailJobs.TryRemove((Number(command, "version", -1), Number(command, "index", -1)), out var job)) TryCancel(job);
    }
    static void TryCancel(CancellationTokenSource job) { try { job.Cancel(); } catch (ObjectDisposedException) { } }
    void CancelObsoleteThumbnails()
    {
        foreach (var pair in thumbnailJobs) if (pair.Key.Version != version) TryCancel(pair.Value);
        CancelObsoleteSticker();
    }
    void StartThumbnail(WechatDbMessage message, int requestedVersion, int index)
    {
        var activeStore = store; var selectedAccount = account;
        if (message.Type == WechatDbMessageType.Emoji && (message.AccountKey != selectedAccount || message.ConversationUsername != chat)) throw new ArgumentException("表情所属账号或会话已变化，请重新选择。");
        var key = (requestedVersion, index);
        if (thumbnailJobs.ContainsKey(key)) return;
        if (thumbnailJobs.Count >= 64) { Post("chat", new { type = "thumbnail", version = requestedVersion, index, data = (string?)null, status = "图片读取繁忙，点击可单独查看。" }); return; }
        var cancellation = OperationCancellation();
        if (!thumbnailJobs.TryAdd(key, cancellation)) { cancellation.Dispose(); return; }
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            bool acquired = false;
            try
            {
                await thumbnailGate.WaitAsync(cancellation.Token); acquired = true;
                if (requestedVersion != Volatile.Read(ref version)) return;
                if (message.Type == WechatDbMessageType.Emoji)
                {
                    var sticker = await LoadStickerThumbnailAsync(message, activeStore, cancellation.Token);
                    await PublishThumbnailAsync(key, cancellation, new { type = "thumbnail", version = requestedVersion, index, data = sticker.Url, status = sticker.Status }, activeStore, selectedAccount);
                    return;
                }
                var result = await LoadMediaAsync(message, cancellation.Token);
                if (result.Mime.StartsWith("video/", StringComparison.Ordinal)) result = await VideoCoverAsync(result.Path, cancellation.Token);
                if (!result.Mime.StartsWith("image/", StringComparison.Ordinal)) throw new ArgumentException("此附件没有可用的图片预览。");
                await PublishThumbnailAsync(key, cancellation, new { type = "thumbnail", version = requestedVersion, index, data = result.Url, status = "已保存图片 · 点击预览" });
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { /* Re-entering the viewport may request it again. */ }
            catch (Exception error) when (error is not OutOfMemoryException)
            {
                await PublishThumbnailAsync(key, cancellation, new { type = "thumbnail", version = requestedVersion, index, data = (string?)null, status = error is ArgumentException or MacAttachmentUnavailableException ? error.Message : "本地附件读取未完成，请重试。" }, activeStore, selectedAccount);
            }
            finally { if (acquired) thumbnailGate.Release(); ((ICollection<KeyValuePair<(int Version, int Index), CancellationTokenSource>>)thumbnailJobs).Remove(new(key, cancellation)); cancellation.Dispose(); }
        }));
    }
    async Task PublishThumbnailAsync((int Version, int Index) key, CancellationTokenSource cancellation, object value, WechatUiCollector.Storage.SqliteMessageStore? expectedStore = null, string? expectedAccount = null)
    {
        await gate.WaitAsync();
        try
        {
            if (!cancellation.IsCancellationRequested && version == key.Version && (expectedStore is null || ReferenceEquals(store, expectedStore)) && (expectedAccount is null || account == expectedAccount) && thumbnailJobs.TryGetValue(key, out var current) && ReferenceEquals(current, cancellation)) Post("chat", value);
        }
        finally { gate.Release(); }
    }
    IDisposable? playbackLease;
    void Playback(bool active)
    {
        if (active) playbackLease ??= PlaybackWorkCoordinator.Shared.Enter();
        else { playbackLease?.Dispose(); playbackLease = null; }
    }
    public (string Path, string Mime)? MediaResource(string id) => mediaResources.TryGetValue(id, out var resource) && (!IsStickerResource(id) || ReadStickerResource(id) is not null) ? resource : null;
    async Task<(string Path, string Mime, string Url)> LoadMediaAsync(WechatDbMessage message, CancellationToken token, bool avatar = false, bool foreground = false)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token); timeout.CancelAfter(TimeSpan.FromSeconds(90));
        try { return await LoadMediaCoreAsync(message, timeout.Token, avatar, foreground); }
        catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new IOException("本地附件读取超时，可重试。"); }
    }
    async Task<(string Path, string Mime, string Url)> LoadMediaCoreAsync(WechatDbMessage message, CancellationToken token, bool avatar = false, bool foreground = false)
    {
        var configured = Options.AttachmentSourceDirectory;
        var sourceBase = string.IsNullOrWhiteSpace(configured)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
            : WechatUiCollector.Configuration.ConfigurationLoader.ResolvePath(configured, directory);
        var accountRoot = Path.GetFileName(Path.TrimEndingDirectorySeparator(sourceBase)) == message.AccountKey ? sourceBase : Path.Combine(sourceBase, message.AccountKey);
        var workers = foreground ? foregroundMediaWorkers : mediaWorkers;
        string path, mime;
        if (avatar)
        {
            var output = await workers.ExchangeAsync(new { archive, action = "avatar", sourceRoot = Path.GetDirectoryName(accountRoot), account = message.AccountKey, chat = message.SenderUsername }, token);
            using var result = JsonDocument.Parse(output); var data = result.RootElement;
            if (Text(data, "status") != "ready") throw new IOException("本地头像未完成读取。");
            path = MacMediaAccess.ValidateFile(Text(data, "path"), [Path.Combine(archive, "media"), accountRoot]); mime = Text(data, "mime");
        }
        else
        {
            var result = await MacMediaAccess.LoadAsync(workers, archive, accountRoot, message, message.Type == WechatDbMessageType.Voice ? "voice" : "attachment", token);
            path = result.Path; mime = result.Mime;
        }
        var id = Guid.NewGuid().ToString("N"); mediaResources[id] = (path, mime);
        if (mediaResources.Count > 256) mediaResources.TryRemove(mediaResources.Keys.First(), out _);
        return (path, mime, "/preview/" + id);
    }
    async Task<(string Path, string Mime, string Url)> VideoCoverAsync(string movie, CancellationToken token)
    {
        string project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
        string bundled = Path.GetFullPath(Path.Combine(project, "../native/ffmpeg"));
        string outputDirectory = Path.Combine(directory, "media", "video-covers");
        ProtectedFileSystem.CreateDirectory(outputDirectory);
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(outputDirectory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        string output = Path.Combine(outputDirectory, Guid.NewGuid().ToString("N") + ".png");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token); timeout.CancelAfter(TimeSpan.FromSeconds(15));
        var start = new ProcessStartInfo(File.Exists(bundled) ? bundled : "/opt/homebrew/bin/ffmpeg") { UseShellExecute = false, RedirectStandardError = true, RedirectStandardOutput = true };
        foreach (var arg in new[] { "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", movie, "-frames:v", "1", "-vf", "scale=640:640:force_original_aspect_ratio=decrease", "-update", "1", output }) start.ArgumentList.Add(arg);
        bool ready = false;
        try
        {
            using var process = Process.Start(start) ?? throw new IOException("视频封面读取未启动。");
            using var cancel = timeout.Token.Register(() => { try { process.Kill(true); } catch (InvalidOperationException) { } });
            var errors = process.StandardError.ReadToEndAsync(timeout.Token); var stdout = process.StandardOutput.ReadToEndAsync(timeout.Token);
            await process.WaitForExitAsync(timeout.Token); await Task.WhenAll(errors, stdout);
            if (process.ExitCode != 0 || !File.Exists(output) || new FileInfo(output).Length > 8 * 1024 * 1024) throw new IOException("本地视频未能生成封面。");
            var header = new byte[8]; using (var file = File.OpenRead(output)) { if (await file.ReadAsync(header, token) != 8 || !header.SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 })) throw new IOException("视频封面格式无效。"); }
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(output, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            var id = Guid.NewGuid().ToString("N"); mediaResources[id] = (output, "image/png");
            if (mediaResources.Count > 256) mediaResources.TryRemove(mediaResources.Keys.First(), out _);
            ready = true; return (output, "image/png", "/preview/" + id);
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new IOException("视频封面读取超时，可重试。"); }
        finally { if (!ready && File.Exists(output)) File.Delete(output); }
    }
    async Task MediaActionAsync(string action, JsonElement command, CancellationToken token)
    {
        int requestedVersion = Number(command, "version", -1), index = Number(command, "index", -1);
        try
        {
            var message = SelectedMessage(command);
            if (action == "thumbnail") { StartThumbnail(message, requestedVersion, index); return; }
            if (action == "sticker") { StartSticker(message, requestedVersion, index); return; }
            if (action == "image") { await OpenImagesAsync(message, token); return; }
            if (action == "file") { await ShowFileLocationAsync(message, token); return; }
            var result = await LoadMediaAsync(message, token, foreground: true);
            Post("chat", new { type = "macNative", command = "media", path = result.Path, voice = message.Type == WechatDbMessageType.Voice });
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            string status = error is ArgumentException or MacAttachmentUnavailableException ? error.Message : error is OperationCanceledException ? "附件读取已取消。" : "本地附件读取未完成，请重试。";
            if (action == "thumbnail") Post("chat", new { type = "thumbnail", version = requestedVersion, index, data = (string?)null, status });
            else Post("chat", new { type = "feedback", version = requestedVersion, index, text = status });
        }
    }
}
