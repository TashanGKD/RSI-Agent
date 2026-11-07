using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace WechatCollector.Mac;

public sealed record MacStickerProbeResult(string Mime, int Width, int Height, int Frames, byte[] ThumbnailPng);
public static class MacStickerProbe
{
    public static async Task<MacStickerProbeResult> InspectAsync(byte[] bytes, CancellationToken token, string? executable = null)
    {
        if (bytes.Length is < 1 or > 8388608) throw new IOException("表情资源超出限制。");
        if (executable is null)
        {
            var project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
            var bundled = Path.GetFullPath(Path.Combine(project, "../native/sticker-probe"));
            executable = File.Exists(bundled) ? bundled : Path.Combine(project, "build/native/sticker-probe");
        }
        if (!File.Exists(executable)) throw new IOException("本地表情预览组件尚未就绪。");
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        start.ArgumentList.Add("--inspect");
        start.Environment.Clear();
        foreach (var name in new[] { "HOME", "TMPDIR", "LANG", "LC_CTYPE" }) if (Environment.GetEnvironmentVariable(name) is { } value) start.Environment[name] = value;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        using var process = Process.Start(start) ?? throw new IOException("表情预览组件未启动。");
        void Stop() { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } }
        using var cancel = deadline.Token.Register(Stop);
        try
        {
            var output = ReadBoundedAsync(process.StandardOutput, 2 * 1024 * 1024, deadline.Token);
            var errors = ReadBoundedAsync(process.StandardError, 16384, deadline.Token); // discard; no private OS descriptions in UI/logs
            await process.StandardInput.BaseStream.WriteAsync(bytes, deadline.Token); process.StandardInput.Close();
            await process.WaitForExitAsync(deadline.Token); var text = await output; await errors;
            if (process.ExitCode != 0) throw new IOException("表情图片格式无法验证。");
            using var json = JsonDocument.Parse(text); var result = json.RootElement;
            if (result.GetProperty("status").GetString() != "ready") throw new IOException("表情图片超出预览范围或格式不支持。");
            string mime = result.GetProperty("mime").GetString() ?? "";
            int width = result.GetProperty("width").GetInt32(), height = result.GetProperty("height").GetInt32(), frames = result.GetProperty("frames").GetInt32();
            if (mime is not ("image/png" or "image/jpeg" or "image/gif" or "image/webp") || width <= 0 || height <= 0 || frames is < 1 or > 300 || (long)width * height > 16_000_000 || (long)width * height * frames > 64_000_000) throw new IOException("表情图片尺寸过大。");
            var thumbnail = Convert.FromBase64String(result.GetProperty("thumbnailPngBase64").GetString() ?? "");
            if (thumbnail.Length is < 24 or > 1048576 || !thumbnail.AsSpan().StartsWith(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 })) throw new IOException("表情缩略图格式不支持。");
            return new(mime, width, height, frames, thumbnail);
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested) { throw new IOException("表情预览处理超时，可重试。"); }
        catch (Exception error) when (error is JsonException or FormatException or KeyNotFoundException or InvalidOperationException) { throw new IOException("表情预览结果无法验证。", error); }
        finally { Stop(); }
    }
    static async Task<string> ReadBoundedAsync(StreamReader reader, int limit, CancellationToken token)
    {
        var output = new StringBuilder(); var buffer = new char[4096]; int count;
        while ((count = await reader.ReadAsync(buffer, token)) > 0) { if (output.Length + count > limit) throw new IOException("表情预览回包超出范围。"); output.Append(buffer, 0, count); }
        return output.ToString();
    }
}
