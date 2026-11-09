using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace WechatCollector.Mac;

public sealed partial class MacArchiveLease
{
    // Names-only preparation. Python owns Unicode equivalence; these labels
    // confer no physical identity or authority to create a path.
    internal static Task<int[]> NormalizeCloneNamesAsync(IReadOnlyList<string> names, CancellationToken token) =>
        NormalizeCloneNamesCoreAsync(names, PrepareAsync, token);

    // Fixture-only transport injection; no production configuration override.
    internal static Task<int[]> NormalizeCloneNamesForTestsAsync(IReadOnlyList<string> names,
        Func<string, CancellationToken, Task<string>> transport, CancellationToken token) =>
        NormalizeCloneNamesCoreAsync(names, transport, token);

    static async Task<int[]> NormalizeCloneNamesCoreAsync(IReadOnlyList<string> names,
        Func<string, CancellationToken, Task<string>> transport, CancellationToken token)
    {
        try
        {
            token.ThrowIfCancellationRequested();
            if (!OperatingSystem.IsMacOS()) throw Invalid();
            _ = Native.OrdinaryUid();
            if (names is null || names.Count is < 1 or > 2048 || transport is null) throw Invalid();
            // Capture every name before the first await, including mutable callers.
            string[] snapshot = names.ToArray();
            if (snapshot.Length is < 1 or > 2048) throw Invalid();
            var utf8 = new UTF8Encoding(false, true);
            foreach (string name in snapshot)
            {
                if (name is null || name.Length == 0 || name is "." or ".." || name.Contains('\0') || name.Contains('/') || utf8.GetByteCount(name) > 255) throw Invalid();
            }
            string nonce = Guid.NewGuid().ToString("N");
            string request = JsonSerializer.Serialize(new { v = 2, op = "normalizeNames", request = nonce, names = snapshot },
                new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
            if (utf8.GetByteCount(request) + 1 > 8192) throw Invalid();
            string raw = await transport(request, token);
            token.ThrowIfCancellationRequested();
            if (raw is null || utf8.GetByteCount(raw) is < 1 or > 8192 || raw.Contains('\0') || !raw.EndsWith('\n') || raw.Count(c => c == '\n') != 1) throw Invalid();
            using var doc = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 4 });
            var value = doc.RootElement;
            Exact(value, ["v", "op", "status", "request", "classes"]);
            if (value.GetProperty("v").GetRawText() != "2" || Text(value,"op") != "normalizeNames" || Text(value,"status") != "normalized" || Text(value,"request") != nonce) throw Invalid();
            var array = value.GetProperty("classes");
            if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() != snapshot.Length) throw Invalid();
            int[] result = new int[snapshot.Length]; int next = 0, index = 0;
            foreach (var item in array.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Number || !item.TryGetInt32(out int label) || label < 0 || label > next || item.GetRawText() != label.ToString(CultureInfo.InvariantCulture)) throw Invalid();
                if (label == next) next++;
                result[index++] = label;
            }
            token.ThrowIfCancellationRequested();
            return result;
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception) { throw Invalid(); }
    }
}
