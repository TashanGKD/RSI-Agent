using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

// This prerequisite only checks files that the historical copy loop would skip.
// It performs no destination repair or credential replacement.
internal static class MacArchiveClonePreflight
{
    internal const string Mismatch = "未完成的归档副本与当前来源不一致；已有文件已保留，请选择新的空保存目录后重试。";

    internal static async Task ValidateAsync(string source, string destination, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        try
        {
            source = Path.GetFullPath(source);
            destination = Path.GetFullPath(destination);
            string accounts = SourcePathProtection.WritablePath(Path.Combine(destination, "accounts"));
            foreach (var entry in MacArchiveLease.CloneAccountEntries(accounts, token))
            {
                token.ThrowIfCancellationRequested();
                // Keep the existing target hardlink/source-path protections even
                // though both hashes themselves only open read-only descriptors.
                string file = entry.Path;
                SourcePathProtection.WritablePath(file);
                string corresponding = file == accounts ? Path.Combine(source, "accounts") :
                    Path.Combine(source, "accounts", Path.GetRelativePath(accounts, file));
                if (entry.Directory)
                {
                    MacArchiveLease.CheckCloneDirectoryCounterpart(corresponding);
                    continue;
                }
                string existing = await MacArchiveLease.HashCloneFileAsync(file, token);
                string current = await MacArchiveLease.HashCloneFileAsync(corresponding, token);
                if (existing != current) throw new IOException(Mismatch);
            }
            token.ThrowIfCancellationRequested();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
        {
            // Do not expose paths, hashes or underlying filesystem errors.
            throw new IOException(Mismatch);
        }
    }
}
