using System.Security.Cryptography;
using System.Text;

namespace WechatCollector.Mac;

public static class BridgeSecurity
{
    public static bool EqualToken(string? candidate, string expected) => candidate is not null && candidate.Length == expected.Length && CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(candidate), Encoding.ASCII.GetBytes(expected));
    public static bool SameInstance(string? candidate, string expected) => !string.IsNullOrEmpty(expected) && string.Equals(candidate, expected, StringComparison.Ordinal);
    public static bool LocalHost(string host, int port) => host == $"127.0.0.1:{port}";
    public static bool SameOrigin(string? origin, int port) => string.IsNullOrEmpty(origin) || origin == $"http://127.0.0.1:{port}";
    public static string? Asset(string path, IReadOnlyDictionary<string, string> files) => files.TryGetValue(path, out var file) ? file : null;
}
