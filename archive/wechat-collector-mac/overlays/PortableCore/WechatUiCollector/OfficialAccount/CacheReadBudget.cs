using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;

namespace WechatUiCollector.OfficialAccount;

internal sealed record CacheReadLimits
{
    internal long MaxDecodedBytes { get; init; } = 64L * 1024 * 1024;
    internal long MaxRetainedHtmlBytes { get; init; } = 32L * 1024 * 1024;
    internal long MaxMetadataBytes { get; init; } = 8L * 1024 * 1024;
    internal int MaxArticles { get; init; } = 4096;
    internal int MaxValues { get; init; } = 4096;
    internal int MaxTraversalEntries { get; init; } = 8192;
    internal int MaxTraversalDepth { get; init; } = 16;
    internal void Validate()
    {
        if (MaxDecodedBytes is < 1 or > 67108864 || MaxRetainedHtmlBytes is < 1 or > 33554432 || MaxMetadataBytes is < 1 or > 8388608
            || MaxArticles is < 1 or > 4096 || MaxValues is < 1 or > 4096 || MaxTraversalEntries is < 1 or > 8192 || MaxTraversalDepth is < 1 or > 16)
            throw new ArgumentOutOfRangeException(nameof(CacheReadLimits));
    }
}
internal sealed record ArticleBodyCacheLimits
{
    internal int MaxHtmlBytes { get; init; } = 8 * 1024 * 1024;
    internal int MaxFileBytes { get; init; } = 64 * 1024 * 1024;
    internal double MaxSeconds { get; init; } = 30;
    internal void Validate()
    { if (MaxHtmlBytes is < 1 or > 8388608 || MaxFileBytes is < 1 or > 67108864 || !double.IsFinite(MaxSeconds) || MaxSeconds <= 0 || MaxSeconds > 30) throw new ArgumentOutOfRangeException(nameof(ArticleBodyCacheLimits)); }
}
internal sealed class CacheResourceLimitException(string code, bool terminal = true) : IOException(code)
{
    internal string Code { get; } = code;
    internal bool Terminal { get; } = terminal;
}
internal sealed class CacheReadContext(CacheReadLimits limits, ProfileHistoryCacheReadOptions options, CancellationToken token)
{
    readonly Stopwatch clock = Stopwatch.StartNew();
    internal CacheReadLimits Limits => limits;
    internal CancellationToken Token => token;
    internal long RawBytes, DecodedBytes, HtmlBytes, MetadataBytes;
    internal int Values, Entries, SkippedLinks;
    readonly HashSet<string> reasons = new(StringComparer.Ordinal);
    internal IReadOnlyCollection<string> Reasons => reasons;
    internal void Require() { token.ThrowIfCancellationRequested(); if (clock.Elapsed.TotalSeconds > options.MaxSeconds) Stop("time-limit"); }
    internal void Stop(string code, bool terminal = true) { reasons.Add(code); throw new CacheResourceLimitException(code, terminal); }
    internal void Note(string code) => reasons.Add(code);
    internal void Decoded(long bytes) { Require(); if (bytes < 0 || bytes > limits.MaxDecodedBytes - DecodedBytes) Stop("decoded-limit"); DecodedBytes += bytes; }
    internal void Metadata(long bytes) { Require(); if (bytes < 0 || bytes > limits.MaxMetadataBytes - MetadataBytes) Stop("metadata-limit"); MetadataBytes += bytes; }
    internal void Html(long bytes) { Require(); if (bytes < 0 || bytes > limits.MaxRetainedHtmlBytes - HtmlBytes) Stop("html-limit"); HtmlBytes += bytes; }
    internal void ValueCapacity() { Require(); if (Values >= limits.MaxValues) Stop("value-limit"); }
    internal void Value() { ValueCapacity(); Values++; }
    internal void Entry(int depth) { Require(); if (depth > limits.MaxTraversalDepth) Stop("depth-limit"); if (Entries >= limits.MaxTraversalEntries) Stop("entry-limit"); Entries++; }
}
