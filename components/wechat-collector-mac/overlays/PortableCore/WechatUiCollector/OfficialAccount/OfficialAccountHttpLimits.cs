using System;

namespace WechatUiCollector.OfficialAccount;

// Internal per-instance test injection only; public constructors remain unchanged.
internal sealed record OfficialAccountHttpLimits
{
    internal static OfficialAccountHttpLimits Default { get; } = new();
    internal int MaxResponseBytes { get; init; } = 8 * 1024 * 1024;
    internal TimeSpan RequestTimeout { get; init; } = TimeSpan.FromSeconds(30);
    internal void Validate(TimeSpan maximumTimeout)
    {
        if (MaxResponseBytes < 1 || MaxResponseBytes > 8 * 1024 * 1024 || RequestTimeout <= TimeSpan.Zero || RequestTimeout > maximumTimeout)
            throw new ArgumentOutOfRangeException(nameof(OfficialAccountHttpLimits), "HTTP limits must be positive and no larger than the safe defaults.");
    }
}
