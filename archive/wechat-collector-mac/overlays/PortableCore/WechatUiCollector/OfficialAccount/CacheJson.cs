using System;
using System.Text;
using System.Text.Json;

namespace WechatUiCollector.OfficialAccount;

internal static class CacheJson
{
    internal static JsonDocument Parse(string text, CacheReadContext context, bool relaxed = false)
    {
        context.Require(); int count = Encoding.UTF8.GetByteCount(text); context.Decoded(count);
        byte[] bytes = Encoding.UTF8.GetBytes(text);
        var reader = new Utf8JsonReader(bytes, new JsonReaderOptions { AllowTrailingCommas = relaxed, CommentHandling = relaxed ? JsonCommentHandling.Skip : JsonCommentHandling.Disallow, MaxDepth = 64 });
        while (reader.Read()) {
            context.Require();
            // CurrentDepth is zero-based for start tokens. DOM MaxDepth32
            // permits starts0..31, including empty containers without a scalar.
            if (reader.CurrentDepth > 32 || ((reader.TokenType is JsonTokenType.StartObject or JsonTokenType.StartArray) && reader.CurrentDepth >= 32))
                context.Stop("json-depth-limit");
            context.Metadata(32);
            // Reserve all later scalar string materialization before DOM/GetString.
            if (reader.TokenType is JsonTokenType.String or JsonTokenType.PropertyName) context.Decoded(2L * reader.ValueSpan.Length);
        }
        return JsonDocument.Parse(bytes, new JsonDocumentOptions { AllowTrailingCommas = relaxed, CommentHandling = relaxed ? JsonCommentHandling.Skip : JsonCommentHandling.Disallow, MaxDepth = 32 });
    }
    internal static int StringBytes(ref Utf8JsonReader reader, int maximum, Action? checkpoint = null)
    {
        ReadOnlySpan<byte> span = reader.ValueSpan; long count = 0;
        for (int i = 0; i < span.Length; i++) {
            if ((i & 4095) == 0) checkpoint?.Invoke();
            byte b = span[i];
            if (b != 92) count++;
            else {
                if (++i >= span.Length) throw new JsonException();
                if (span[i] != (byte)'u') count++;
                else {
                    if (i + 4 >= span.Length) throw new JsonException(); int code = Hex(span.Slice(i + 1, 4)); i += 4;
                    if (code is >= 0xd800 and <= 0xdbff) {
                        if (i + 6 >= span.Length || span[i + 1] != 92 || span[i + 2] != (byte)'u') throw new JsonException();
                        int low = Hex(span.Slice(i + 3, 4)); if (low is < 0xdc00 or > 0xdfff) throw new JsonException(); i += 6; count += 4;
                    }
                    else if (code is >= 0xdc00 and <= 0xdfff) throw new JsonException();
                    else count += code < 128 ? 1 : code < 2048 ? 2 : 3;
                }
            }
            if (count > maximum) throw new CacheResourceLimitException("body-html-limit");
        }
        return (int)count;
    }
    static int Hex(ReadOnlySpan<byte> span) { int value = 0; foreach (byte b in span) { int n = b is >= 48 and <= 57 ? b - 48 : b is >= 65 and <= 70 ? b - 55 : b is >= 97 and <= 102 ? b - 87 : -1; if (n < 0) throw new JsonException(); value = value * 16 + n; } return value; }
}
