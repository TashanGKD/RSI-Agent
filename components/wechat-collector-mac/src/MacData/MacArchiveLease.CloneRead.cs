using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace WechatCollector.Mac;

public sealed partial class MacArchiveLease
{
    // The accepted Darwin stat ABI, fixed-arity openat and parent-chain checks
    // live in MacArchiveLease.cs; no coordinator preparation or lock is involved.
    internal static IEnumerable<(string Path, bool Directory)> CloneAccountEntries(string path, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        path = Canonical(path);
        using var chain = new Chain(path, missingOk: true);
        if (!chain.Complete) yield break;
        yield return (path, true);
        foreach (string entry in Directory.EnumerateFileSystemEntries(path))
        {
            token.ThrowIfCancellationRequested();
            chain.Check();
            var pin = Native.StatAt(chain.Fd, Path.GetFileName(entry));
            switch (pin.Mode & 0xf000)
            {
                case 0x4000:
                    foreach (var file in CloneAccountEntries(entry, token)) yield return file;
                    break;
                case 0x8000:
                    yield return (entry, false);
                    break;
                default: throw Invalid();
            }
            chain.Check();
        }
        chain.Check();
    }

    internal static void CheckCloneDirectoryCounterpart(string path)
    {
        // Missing source directories are harmless until a target file needs one.
        using var chain = new Chain(Canonical(path), missingOk: true);
        chain.Check();
    }

    internal static Task<string> HashCloneFileAsync(string path, CancellationToken token) =>
        HashCloneFileCoreAsync(path, token, null);

    // Deterministic private-fixture observation after an actual read. The public
    // clone path cannot select this callback, a root or a home override.
    internal static Task<string> HashCloneFileForTestsAsync(string path, CancellationToken token, Action afterRead) =>
        HashCloneFileCoreAsync(path, token, afterRead);

    static async Task<string> HashCloneFileCoreAsync(string path, CancellationToken token, Action? afterRead)
    {
        token.ThrowIfCancellationRequested();
        if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException();
        uint owner = Native.OrdinaryUid();
        path = Canonical(path);
        string leaf = Path.GetFileName(path);
        if (leaf.Length == 0) throw Invalid();
        using var chain = new Chain(Path.GetDirectoryName(path)!);
        var before = Native.StatAt(chain.Fd, leaf);
        RequireCloneRegular(before, owner); // reject FIFOs/devices before reading
        int fd = Native.OpenAt(chain.Fd, leaf, 0x100 | 4 | 0x1000000); // RDONLY, NOFOLLOW, NONBLOCK, CLOEXEC; no create
        if (fd < 0) throw Invalid();
        try
        {
            Native.CheckFlags(fd, false);
            CloneReadMatch(before, Native.FStat(fd));
            chain.Check();
            using var handle = new SafeFileHandle((IntPtr)fd, ownsHandle: false);
            using var stream = new FileStream(handle, FileAccess.Read, 64 * 1024, isAsync: false);
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            byte[] buffer = new byte[64 * 1024];
            for (;;)
            {
                token.ThrowIfCancellationRequested();
                int read = await stream.ReadAsync(buffer, token);
                if (read == 0) break;
                hash.AppendData(buffer, 0, read);
                afterRead?.Invoke();
            }
            token.ThrowIfCancellationRequested();
            CloneReadMatch(before, Native.FStat(fd));
            CloneReadMatch(before, Native.StatAt(chain.Fd, leaf));
            chain.Check();
            return Convert.ToHexString(hash.GetHashAndReset());
        }
        finally { Native.Close(fd); }
    }

    static void RequireCloneRegular(Native.Stat value, uint owner)
    {
        if ((value.Mode & 0xf000) != 0x8000 || value.Uid != owner) throw Invalid();
    }
    static void CloneReadMatch(Native.Stat before, Native.Stat after)
    {
        Match(before, after);
        if (before.Size != after.Size || before.NLink != after.NLink ||
            before.MTime != after.MTime || before.MTimeNs != after.MTimeNs ||
            before.CTime != after.CTime || before.CTimeNs != after.CTimeNs) throw Invalid();
    }
}
