using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.Win32.SafeHandles;
using WechatUiCollector.Safety;

namespace WechatUiCollector.OfficialAccount;

internal static class CacheFile
{
    internal static bool IsLink(string path) => (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
    internal static FileStream OpenRead(string path)
    {
        path = SourcePathProtection.CanonicalMacSystemPath(Path.GetFullPath(path));
        for (string? part = path; !string.IsNullOrEmpty(part); part = Path.GetDirectoryName(part))
            if (IsLink(part)) throw new IOException("cache-link-rejected");
        if (!OperatingSystem.IsMacOS()) return new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        // Same Darwin NOFOLLOW_ANY/NONBLOCK/CLOEXEC pattern as the existing
        // PlaybackWorkCoordinator; guards parents+leaf and rejects FIFO swaps.
        int fd = Open(path, 4 | 0x01000000 | 0x20000000);
        if (fd < 0) throw new IOException("cache-open-rejected");
        var handle = new SafeFileHandle((IntPtr)fd, true);
        try {
            int status = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? FStatInode64(fd, out var info) : FStat(fd, out info);
            if (status != 0 || (info.Mode & 0xf000) != 0x8000 || info.Links != 1) throw new IOException("cache-handle-rejected");
            return new FileStream(handle, FileAccess.Read);
        }
        catch { handle.Dispose(); throw; }
    }
    // Actual opened-file boundary; the stale pre-open FileInfo is never trusted.
    // A final sentinel rejects growth without reallocating or parsing a prefix.
    internal static byte[] ReadOpened(FileStream opened, long maximumBytes, long remainingRawBytes, CancellationToken token, Action? checkpoint = null, Action<long>? reserve = null)
    {
        token.ThrowIfCancellationRequested(); checkpoint?.Invoke(); long length = opened.Length;
        if (length > maximumBytes) throw new CacheResourceLimitException("raw-file-limit", false);
        if (length > remainingRawBytes) throw new CacheResourceLimitException("raw-total-limit");
        if (length < 0 || length > int.MaxValue) throw new CacheResourceLimitException("raw-file-limit", false);
        reserve?.Invoke(length);
        byte[] bytes = new byte[(int)length]; int used = 0;
        while (used < bytes.Length) {
            token.ThrowIfCancellationRequested(); checkpoint?.Invoke();
            int read = opened.Read(bytes, used, Math.Min(65536, bytes.Length - used));
            if (read == 0) throw new IOException("cache-file-changed"); used += read;
        }
        token.ThrowIfCancellationRequested(); checkpoint?.Invoke();
        Span<byte> sentinel = stackalloc byte[1];
        if (opened.Read(sentinel) != 0 || opened.Length != length) throw new IOException("cache-file-changed");
        return bytes;
    }
    [StructLayout(LayoutKind.Explicit, Size = 256)] struct DarwinStat { [FieldOffset(4)] public ushort Mode; [FieldOffset(6)] public ushort Links; }
    [DllImport("libSystem.B.dylib", EntryPoint = "open", SetLastError = true)] static extern int Open([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat", SetLastError = true)] static extern int FStat(int fd, out DarwinStat info);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat$INODE64", SetLastError = true)] static extern int FStatInode64(int fd, out DarwinStat info);
}
