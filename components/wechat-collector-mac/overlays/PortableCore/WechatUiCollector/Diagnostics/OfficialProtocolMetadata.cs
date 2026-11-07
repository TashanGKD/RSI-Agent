using System.Collections.Generic;

namespace WechatUiCollector.Diagnostics;

// Select only fixed scalar metadata before any serialization. Never enumerate
// arbitrary payload dictionaries, stringify objects, or retain the body/URLs.
internal static class OfficialProtocolMetadata
{
    internal static Dictionary<string, object?> Build(IReadOnlyDictionary<string, object?> properties)
    {
        string stage = "unknown";
        if (properties.TryGetValue("stage", out object? rawStage) && rawStage is string suppliedStage && suppliedStage.Length <= 32)
            stage = suppliedStage switch {
                "getmsg-request" => "getmsg-request",
                "getmsg" => "getmsg",
                "article-identity" => "article-identity",
                "album-history" => "album-history",
                "captured-credentials" => "captured-credentials",
                _ => "unknown"
            };
        var metadata = new Dictionary<string, object?> {
            ["metadataVersion"] = 1,
            ["stage"] = stage
        };
        if (properties.TryGetValue("httpStatus", out object? rawStatus) && rawStatus is int status && status is >= 100 and <= 599)
            metadata["httpStatus"] = status;
        if (properties.TryGetValue("offset", out object? rawOffset) && rawOffset is int offset && offset >= 0)
            metadata["offset"] = offset;
        if (properties.TryGetValue("elapsedMs", out object? rawElapsed))
        {
            if (rawElapsed is long elapsed && elapsed >= 0) metadata["elapsedMs"] = elapsed;
            else if (rawElapsed is int elapsedInt && elapsedInt >= 0) metadata["elapsedMs"] = elapsedInt;
        }
        if (properties.TryGetValue("responseBody", out object? rawBody) && rawBody is string body)
            metadata["responseCharacters"] = body.Length;
        return metadata;
    }
}
