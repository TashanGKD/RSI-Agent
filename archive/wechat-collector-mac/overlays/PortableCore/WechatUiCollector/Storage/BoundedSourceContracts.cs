using System;
using System.Collections.Generic;
using WechatUiCollector.WechatDb;

namespace WechatUiCollector.Storage;

internal enum PublisherSourceLane { Rows = 1, Changes = 2 }
internal enum PublisherSourceFilter { AppMessages = 1, ArticleShares = 2 }
internal enum BoundedSourceOutcome { Ready, MissingRaw, MissingRecord, Invalid, Unsupported, Limit }
internal enum BoundedRawOutcome { Ready, Missing, InvalidStorage, CompressedLimit, DecodedLimit, InvalidUtf8, Corrupt }
internal sealed record BoundedRawContent(BoundedRawOutcome Outcome, string? Text, int CompressedBytes, int DecodedBytes);
internal sealed record BoundedSourceRecord(RecordIdentity? Identity, WechatDbMessage? Message, BoundedSourceOutcome Outcome, string Code, string Operation);
internal sealed record BoundedSourcePage(IReadOnlyList<BoundedSourceRecord> Records, string Cursor, bool RoundCompleted,
    int VisitedKeys, long RowThrough, long ChangeThrough, long CompressedBytes, long DecodedBytes, long MetadataBytes, bool PageLimitReached);
internal sealed class PublisherSourceResetRequiredException : InvalidOperationException
{ internal PublisherSourceResetRequiredException() : base("publisher-source-reset-required") { } }
internal sealed record BoundedSourceLimits
{
    internal int MaximumVisitedKeys { get; init; } = 32;
    internal int MaximumCompressedBytes { get; init; } = 64 * 1024;
    internal int MaximumDecodedBytes { get; init; } = 256 * 1024;
    internal int MaximumScalarBytes { get; init; } = 8192;
    internal int MaximumPageCompressedBytes { get; init; } = 2 * 1024 * 1024;
    internal int MaximumPageDecodedBytes { get; init; } = 8 * 1024 * 1024;
    internal int MaximumPageMetadataBytes { get; init; } = 256 * 1024;
}
