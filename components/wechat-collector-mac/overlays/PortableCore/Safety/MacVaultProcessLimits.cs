using System;

namespace WechatUiCollector.Safety;

// Internal lower-only test injection. The master-key stdout invariant is always32 bytes.
internal sealed record MacVaultProcessLimits
{
    internal static MacVaultProcessLimits Default { get; } = new();
    internal TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(5);
    internal int MaximumStderrBytes { get; init; } = 8 * 1024;
    internal void Validate()
    {
        if (Timeout <= TimeSpan.Zero || Timeout > TimeSpan.FromSeconds(5) || MaximumStderrBytes < 1 || MaximumStderrBytes > 8 * 1024)
            throw new ArgumentOutOfRangeException(nameof(MacVaultProcessLimits),"Vault process limits must be positive and cannot exceed safe defaults.");
    }
}
