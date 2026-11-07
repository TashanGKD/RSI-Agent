using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace WechatUiCollector.Safety;

// Explicit user-selected associations may follow a link, but must resolve to
// an ordinary file. Opening nonblocking before fstat also handles FIFO swaps.
internal static class LocalAssetFile
{
    private static readonly bool DisableFileLocking = ReadDisableFileLocking();

    internal static FileStream OpenRead(string path)
    {
        if (!OperatingSystem.IsMacOS())
            return new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);

        ArgumentNullException.ThrowIfNull(path);
        if (path.Length == 0 || path.Contains('\0')) throw new ArgumentException("文件路径无效。", nameof(path));
        int descriptor = Open(path, 0x00000004 | 0x01000000); // O_RDONLY | O_NONBLOCK | O_CLOEXEC
        if (descriptor < 0) throw Unavailable();
        var handle = new SafeFileHandle((IntPtr)descriptor, ownsHandle: true);
        try
        {
            DarwinStat metadata;
            int result = RuntimeInformation.ProcessArchitecture == Architecture.X64
                ? FStatInode64(descriptor, out metadata) : FStat(descriptor, out metadata);
            if (result != 0 || (metadata.Mode & 0xf000) != 0x8000) throw Unavailable();
            // Match the shipped runtime's FileShare.Read behavior: only EAGAIN
            // rejects a shared nonblocking flock; unsupported locks are allowed.
            if (!DisableFileLocking && Flock(descriptor, 0x01 | 0x04) != 0
                && Marshal.GetLastPInvokeError() == 35) throw Unavailable();
            return new FileStream(handle, FileAccess.Read);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }

    private static bool ReadDisableFileLocking()
    {
        if (AppContext.TryGetSwitch("System.IO.DisableFileLocking", out bool disabled)) return disabled;
        string? value = Environment.GetEnvironmentVariable("DOTNET_SYSTEM_IO_DISABLEFILELOCKING");
        return string.Equals(value, "true", StringComparison.OrdinalIgnoreCase) || value == "1";
    }

    private static IOException Unavailable() => new IOException("无法读取普通附件文件。");

    [StructLayout(LayoutKind.Explicit, Size = 256)]
    private struct DarwinStat { [FieldOffset(4)] public ushort Mode; }

    [DllImport("libSystem.B.dylib", EntryPoint = "open", SetLastError = true)]
    private static extern int Open([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat", SetLastError = true)]
    private static extern int FStat(int descriptor, out DarwinStat metadata);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat$INODE64", SetLastError = true)]
    private static extern int FStatInode64(int descriptor, out DarwinStat metadata);
    [DllImport("libSystem.B.dylib", EntryPoint = "flock", SetLastError = true)]
    private static extern int Flock(int descriptor, int operation);
}
