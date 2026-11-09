using System.Text.Json;
using System.Text.RegularExpressions;
using WechatUiCollector.Diagnostics;

namespace WechatCollector.Mac;

// The original filter handles Windows profiles. Preserve the same diagnostic
// context while also removing the account segment of Unix profile paths.
internal static class MacDiagnosticsPrivacy
{
    public static string Scrub(string text)
    {
        text = LogPrivacy.Scrub(text);
        try { return Regex.Replace(text, @"/(Users|home)/[^/\s\""'<>]+", "/$1/<redacted>", RegexOptions.CultureInvariant, TimeSpan.FromSeconds(1)); }
        catch (RegexMatchTimeoutException) { return "[redacted: oversized text]"; }
    }
    public static AppLogRecord Record(AppLogRecord record) => record with {
        Message = Scrub(record.Message), Component = Scrub(record.Component), EventId = Scrub(record.EventId),
        OperationName = record.OperationName is null ? null : Scrub(record.OperationName),
        Properties = (IReadOnlyDictionary<string, object?>)(LogPrivacy.Value(JsonSerializer.SerializeToElement(record.Properties), 0, Scrub) ?? new Dictionary<string, object?>()),
        Exception = Exception(record.Exception)
    };
    static ExceptionLogRecord? Exception(ExceptionLogRecord? error) => error is null ? null : error with { Message = Scrub(error.Message), StackTrace = error.StackTrace is null ? null : Scrub(error.StackTrace), InnerException = Exception(error.InnerException) };
}
