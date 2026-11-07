using System;
using System.Collections.Generic;
using System.Text;

namespace WechatUiCollector.WechatDb;

// Observed Mac emoji attributes contain this bounded locale-label envelope.
// Unknown formats stay untouched; this is deliberately not a general protobuf decoder.
internal static class MacEmojiDescription
{
    private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

    public static string? DecodeOrKeep(string? value)
    {
        if (string.IsNullOrEmpty(value) || value.Length > 4096 || value.Length % 4 != 0)
            return value;
        foreach (char c in value)
            if (!(c is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9' or '+' or '/' or '='))
                return value;
        Span<byte> buffer = stackalloc byte[3072];
        if (!Convert.TryFromBase64String(value, buffer, out int length) || length == 0
            || Convert.ToBase64String(buffer.Slice(0, length)) != value)
            return value;
        ReadOnlySpan<byte> payload = buffer.Slice(0, length);
        var labels = new Dictionary<string, string>(StringComparer.Ordinal);
        int offset = 0, entries = 0;
        try
        {
            while (offset < payload.Length)
            {
                if (++entries > 32 || !ReadField(payload, ref offset, out int field, out var entry) || field != 1)
                    return value;
                string? locale = null, label = null;
                int entryOffset = 0;
                while (entryOffset < entry.Length)
                {
                    if (!ReadField(entry, ref entryOffset, out int part, out var text)) return value;
                    if (part == 1 && locale == null) locale = StrictUtf8.GetString(text);
                    else if (part == 2 && label == null) label = StrictUtf8.GetString(text);
                    else return value;
                }
                if (locale is not ("default" or "zh_cn" or "zh_tw") || label == null || labels.ContainsKey(locale))
                    return value;
                foreach (char c in label) if (char.IsControl(c)) return value;
                labels.Add(locale, label);
            }
        }
        catch (DecoderFallbackException) { return value; }
        foreach (string locale in new[] { "zh_cn", "default", "zh_tw" })
            if (labels.TryGetValue(locale, out string? label) && !string.IsNullOrWhiteSpace(label)) return label;
        return value;
    }

    private static bool ReadField(ReadOnlySpan<byte> input, ref int offset, out int field, out ReadOnlySpan<byte> body)
    {
        field = 0; body = default;
        if (!ReadVarint(input, ref offset, out int tag) || (tag & 7) != 2 || (tag >> 3) == 0
            || !ReadVarint(input, ref offset, out int length) || length > input.Length - offset)
            return false;
        field = tag >> 3; body = input.Slice(offset, length); offset += length;
        return true;
    }

    private static bool ReadVarint(ReadOnlySpan<byte> input, ref int offset, out int value)
    {
        value = 0;
        for (int shift = 0; shift <= 28 && offset < input.Length; shift += 7)
        {
            byte current = input[offset++];
            if (shift == 28 && current > 7) return false;
            value |= (current & 127) << shift;
            if ((current & 128) == 0) return shift == 0 || current != 0;
        }
        return false;
    }
}
