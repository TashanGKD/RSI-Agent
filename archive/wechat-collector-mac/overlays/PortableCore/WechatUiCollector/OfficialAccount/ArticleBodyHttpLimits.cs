using System;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace WechatUiCollector.OfficialAccount;

// Internal injection preserves every existing public constructor/method call, including new(null).
internal sealed record ArticleBodyHttpLimits
{
    internal static ArticleBodyHttpLimits Default { get; } = new();
    internal int MaxHtmlBytes { get; init; } = 8 * 1024 * 1024;
    internal long MaxImageBytes { get; init; } = 32L * 1024 * 1024;
    internal long MaxArticleImageBytes { get; init; } = 256L * 1024 * 1024;
    internal int MaxImages { get; init; } = 512;
    internal TimeSpan RequestTimeout { get; init; } = TimeSpan.FromSeconds(30);
    internal TimeSpan ArticleTimeout { get; init; } = TimeSpan.FromMinutes(5);

    internal void Validate()
    {
        if (MaxHtmlBytes < 1 || MaxHtmlBytes > 8 * 1024 * 1024 || MaxImageBytes < 64 || MaxImageBytes > 32L * 1024 * 1024 ||
            MaxArticleImageBytes < 64 || MaxArticleImageBytes > 256L * 1024 * 1024 || MaxImages < 1 || MaxImages > 512 ||
            RequestTimeout <= TimeSpan.Zero || RequestTimeout > TimeSpan.FromSeconds(30) ||
            ArticleTimeout <= TimeSpan.Zero || ArticleTimeout > TimeSpan.FromMinutes(5))
            throw new ArgumentOutOfRangeException(nameof(ArticleBodyHttpLimits), "HTTP resource limits must be positive and no larger than the safe defaults.");
    }
}

internal sealed class ArticleBodyLimitException(string message) : IOException(message) { }

internal static class ArticleBodyBoundedHttp
{
    internal static void RejectDeclaredLength(HttpContent content, long maximum, string resource)
    {
        if (content.Headers.ContentLength is long declared && declared > maximum)
            throw new ArticleBodyLimitException($"{resource}声明长度 {declared} 字节超过限额 {maximum} 字节");
    }

    internal static async Task<string> ReadHtmlAsync(HttpContent content, int maximum, CancellationToken token)
    {
        RejectDeclaredLength(content, maximum, "HTML");
        await using Stream source = await content.ReadAsStreamAsync(token).ConfigureAwait(false);
        // Exactly one bounded payload buffer; no MemoryStream growth or ToArray copy.
        byte[] bytes = new byte[maximum + 1];
        int used = 0;
        while (used < bytes.Length)
        {
            int count = await source.ReadAsync(bytes.AsMemory(used, Math.Min(65536, bytes.Length - used)), token).ConfigureAwait(false);
            if (count == 0) return Decode(bytes, used, content.Headers.ContentType?.CharSet);
            used += count;
            if (used > maximum) throw new ArticleBodyLimitException($"HTML实际长度超过限额 {maximum} 字节");
        }
        throw new ArticleBodyLimitException($"HTML实际长度超过限额 {maximum} 字节");
    }

    private static string Decode(byte[] bytes, int length, string? charset)
    {
        Encoding encoding;
        int skip = 0;
        if (!string.IsNullOrEmpty(charset))
        {
            // Matches HttpContent.ReadAsStringAsync: explicit charset has priority; strip matching BOM.
            encoding = Encoding.GetEncoding(charset.Trim('"'));
            var preamble = encoding.GetPreamble();
            if (preamble.Length <= length && bytes.AsSpan(0, preamble.Length).SequenceEqual(preamble)) skip = preamble.Length;
        }
        else if (length >= 4 && bytes[0] == 0xff && bytes[1] == 0xfe && bytes[2] == 0 && bytes[3] == 0)
        { encoding = Encoding.UTF32; skip = 4; }
        else if (length >= 4 && bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 0xfe && bytes[3] == 0xff)
        { encoding = new UTF32Encoding(true, true); skip = 4; }
        else if (length >= 3 && bytes[0] == 0xef && bytes[1] == 0xbb && bytes[2] == 0xbf)
        { encoding = Encoding.UTF8; skip = 3; }
        else if (length >= 2 && bytes[0] == 0xff && bytes[1] == 0xfe)
        { encoding = Encoding.Unicode; skip = 2; }
        else if (length >= 2 && bytes[0] == 0xfe && bytes[1] == 0xff)
        { encoding = Encoding.BigEndianUnicode; skip = 2; }
        else encoding = Encoding.UTF8;
        return encoding.GetString(bytes, skip, length - skip);
    }
}
