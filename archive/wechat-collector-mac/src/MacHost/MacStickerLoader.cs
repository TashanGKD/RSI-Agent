using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using WechatUiCollector.Safety;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed record MacStickerData(byte[] Bytes, MacStickerProbeResult Image, string Path, string ThumbnailPath);
public sealed class MacStickerLoader(string assetDirectory,
    Func<WechatDbMessage, CancellationToken, Task<byte[]?>> local,
    Func<byte[], CancellationToken, Task<MacStickerProbeResult>> probe,
    Func<Uri, string, CancellationToken, Task<byte[]>>? download = null)
{
    readonly string assets = SourcePathProtection.WritablePath(assetDirectory);
    readonly object cacheLock = new();
    readonly Dictionary<(string Account, string Hash), MacStickerData> cache = new();
    readonly Queue<(string Account, string Hash)> order = new();
    long memoryBytes;
    public async Task<MacStickerData?> LoadAsync(WechatDbMessage message, bool allowDownload, CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); var card = WechatDbCard.Read(message);
        if (message.Type != WechatDbMessageType.Emoji || !Regex.IsMatch(message.AccountKey, @"\A[A-Za-z0-9_-]{1,256}\z") || string.IsNullOrEmpty(message.ConversationUsername) || message.ServerId == 0 || card.EmojiHash is not { } rawHash || !Regex.IsMatch(rawHash, @"\A[a-fA-F0-9]{32}\z")) throw new ArgumentException("表情缺少可验证的消息或资源标识。");
        string hash = rawHash.ToLowerInvariant(); var key = (message.AccountKey, hash);
        string path = CachePath(message.AccountKey, hash); byte[]? bytes = null;
        MacStickerData? stored; lock (cacheLock) cache.TryGetValue(key, out stored);
        if (stored is not null)
        {
            // A memory hit never grants a changed on-disk path. Restore missing
            // or modified owned cache bytes from the previously verified data.
            var existing = File.Exists(path) ? await WechatEmojiCache.ReadAsync(assets, message.AccountKey, hash, null, token) : null;
            if (existing is null) await SaveAsync(message.AccountKey, hash, stored.Bytes, path, token);
            SourcePathProtection.WritablePath(stored.ThumbnailPath);
            if (!await ThumbnailMatchesAsync(stored.ThumbnailPath, stored.Image.ThumbnailPng, token))
                await AtomicBytesAsync(stored.ThumbnailPath, stored.Image.ThumbnailPng, token);
            return stored;
        }
        if (File.Exists(path))
        {
            MacMediaAccess.ValidateFile(path, [assets]);
            bytes = await WechatEmojiCache.ReadAsync(assets, message.AccountKey, hash, null, token);
        }
        if (bytes is null)
        {
            try { bytes = await local(message, token); }
            catch (Exception error) when (error is IOException or ArgumentException) { /* A verified local miss is not a network grant. */ }
            if (bytes is not null && !Verified(bytes, hash)) bytes = null;
        }
        if (bytes is null && allowDownload)
        {
            var url = card.EmojiUrl;
            if (url is null) throw new IOException("本地未保存，且消息没有有效表情下载地址。");
            bytes = await (download ?? DefaultDownload)(url, hash, token);
        }
        if (bytes is null) return null;
        if (!Verified(bytes, hash)) throw new IOException("表情内容与消息标识不一致。");
        var image = await probe(bytes, token); token.ThrowIfCancellationRequested();
        if (image.Frames is < 1 or > 300 || image.Width <= 0 || image.Height <= 0 || (long)image.Width * image.Height > 16_000_000 || (long)image.Width * image.Height * image.Frames > 64_000_000 || image.Mime is not ("image/png" or "image/jpeg" or "image/gif" or "image/webp") || image.ThumbnailPng.Length is < 24 or > 1048576) throw new IOException("表情图片超出预览范围。");
        // Preserve the original account/hash cache layout, but stage its saver
        // so cancellation cannot truncate a previously verified cache file.
        await SaveAsync(message.AccountKey, hash, bytes, path, token);
        var thumbnail = SourcePathProtection.WritablePath(Path.Combine(assets, "sticker-thumbnails", AccountPart(message.AccountKey), hash + ".png"));
        await AtomicBytesAsync(thumbnail, image.ThumbnailPng, token);
        var result = new MacStickerData(bytes, image, path, thumbnail);
        lock (cacheLock)
        {
            if (cache.TryGetValue(key, out var existing)) return existing;
            long size = bytes.Length + image.ThumbnailPng.Length;
            while (memoryBytes + size > 16 * 1024 * 1024 && order.TryDequeue(out var oldest))
                if (cache.Remove(oldest, out var removed)) memoryBytes -= removed.Bytes.Length + removed.Image.ThumbnailPng.Length;
            cache[key] = result; order.Enqueue(key); memoryBytes += size;
        }
        return result;
    }
    static bool Verified(byte[] bytes, string hash) => bytes.Length is > 0 and <= 8388608 && Convert.ToHexString(MD5.HashData(bytes)).Equals(hash, StringComparison.OrdinalIgnoreCase);
    static async Task<bool> ThumbnailMatchesAsync(string path, byte[] expected, CancellationToken token)
    {
        try
        {
            await using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite, 8192, useAsync: true);
            // Never size a buffer from a mutable file. A verified thumbnail is
            // at most 1MiB, and a replacement of any other size is a cache miss.
            if (input.Length != expected.Length) return false;
            var buffer = new byte[Math.Min(8192, expected.Length)]; int offset = 0;
            while (offset < expected.Length)
            {
                int count = await input.ReadAsync(buffer.AsMemory(0, Math.Min(buffer.Length, expected.Length - offset)), token);
                if (count == 0 || !buffer.AsSpan(0, count).SequenceEqual(expected.AsSpan(offset, count))) return false;
                offset += count;
            }
            SourcePathProtection.WritablePath(path);
            return input.Length == expected.Length && await input.ReadAsync(buffer.AsMemory(0, 1), token) == 0;
        }
        catch (IOException) { return false; }
    }
    static Task<byte[]> DefaultDownload(Uri url, string hash, CancellationToken token) => WechatEmojiPreview.DownloadAsync(url, hash, token);
    static string AccountPart(string account) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(account)));
    string CachePath(string account, string hash) => SourcePathProtection.WritablePath(Path.Combine(assets, "stickers", AccountPart(account), hash));
    async Task SaveAsync(string account, string hash, byte[] bytes, string destination, CancellationToken token)
    {
        var staging = SourcePathProtection.WritablePath(Path.Combine(assets, ".sticker-writing-" + Guid.NewGuid().ToString("N")));
        ProtectedFileSystem.CreateDirectory(staging);
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(staging, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        try
        {
            await WechatEmojiCache.SaveAsync(staging, account, hash, bytes, token);
            var temporary = Path.Combine(staging, "stickers", AccountPart(account), hash);
            ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(destination)!); SourcePathProtection.WritablePath(destination);
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            token.ThrowIfCancellationRequested(); ProtectedFileSystem.Move(temporary, destination, overwrite: true);
        }
        finally { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
    }
    static async Task AtomicBytesAsync(string destination, byte[] bytes, CancellationToken token)
    {
        ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(destination)!); var temporary = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { await ProtectedFileSystem.WriteAllBytesAsync(temporary, bytes, token); if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite); token.ThrowIfCancellationRequested(); ProtectedFileSystem.Move(temporary, destination, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
