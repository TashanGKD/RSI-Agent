using Microsoft.Win32.SafeHandles;
using System.Runtime.InteropServices;

namespace WechatCollector.Mac;

// Open every component relative to its held parent descriptor. A last-minute
// FIFO/symlink replacement cannot block open or redirect the verification read.
// The held regular-file descriptor is the only stream passed to Core.
sealed class MacFileLocationRead : IDisposable
{
    const int NonBlock = 0x4, NoFollow = 0x100, DirectoryOnly = 0x100000, CloseOnExec = 0x1000000;
    readonly DarwinStat initial;
    public FileStream Stream { get; }
    MacFileLocationRead(FileStream stream, DarwinStat identity) { Stream = stream; initial = identity; }
    public static (long Size, DateTime LastWriteTimeUtc)? RegularInfo(string path)
    {
        RequireMac();
        int result = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? LStatInode64(path, out var value) : LStat(path, out value);
        if (result != 0) ThrowNative(path);
        return (value.Mode & 0xf000) == 0x8000 ? (value.Size, DateTimeOffset.FromUnixTimeSeconds(value.ModifiedSeconds).UtcDateTime.AddTicks(value.ModifiedNanoseconds / 100)) : null;
    }
    public static MacFileLocationRead Open(string path)
    {
        RequireMac();
        if (!Path.IsPathFullyQualified(path) || path.Contains('\0')) throw new IOException("文件位置无法验证。");
        SafeFileHandle? handle = null;
        try
        {
            int descriptor = OpenNative("/", NonBlock | NoFollow | CloseOnExec | DirectoryOnly);
            if (descriptor < 0) ThrowNative(path);
            handle = new SafeFileHandle((IntPtr)descriptor, true);
            var parts = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
            for (int index = 0; index < parts.Length; index++)
            {
                if (parts[index] is "." or "..") throw new IOException("文件位置无法验证。");
                descriptor = OpenAt(handle.DangerousGetHandle().ToInt32(), parts[index], NonBlock | NoFollow | CloseOnExec | (index + 1 < parts.Length ? DirectoryOnly : 0));
                if (descriptor < 0) ThrowNative(path);
                var next = new SafeFileHandle((IntPtr)descriptor, true); handle.Dispose(); handle = next;
            }
            var identity = StatRegular(handle);
            var stream = new FileStream(handle, FileAccess.Read, 131072, isAsync: false);
            handle = null; // FileStream now owns this already checked descriptor.
            return new MacFileLocationRead(stream, identity);
        }
        finally { handle?.Dispose(); }
    }
    public void EnsureCurrent(string path)
    {
        var held = StatRegular(Stream.SafeFileHandle);
        int result = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? LStatInode64(path, out var current) : LStat(path, out current);
        if (result != 0) ThrowNative(path);
        if ((current.Mode & 0xf000) != 0x8000 || !Same(initial, held) || !Same(held, current)) throw new IOException("文件在核对期间已变化，请重新查找。");
    }
    static bool Same(DarwinStat a, DarwinStat b) => a.Device == b.Device && a.Inode == b.Inode && a.Size == b.Size && a.ModifiedSeconds == b.ModifiedSeconds && a.ModifiedNanoseconds == b.ModifiedNanoseconds;
    static DarwinStat StatRegular(SafeFileHandle handle)
    {
        int result = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? FStatInode64(handle.DangerousGetHandle().ToInt32(), out var value) : FStat(handle.DangerousGetHandle().ToInt32(), out value);
        if (result != 0 || (value.Mode & 0xf000) != 0x8000 || value.Size < 0) throw new IOException("本地附件不是普通文件。");
        return value;
    }
    static void RequireMac() { if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException("文件描述符验证需要macOS。"); }
    static void ThrowNative(string path)
    {
        int code = Marshal.GetLastWin32Error();
        if (code is 1 or 13) throw new UnauthorizedAccessException("没有文件访问权限。");
        if (code == 2) throw new FileNotFoundException("文件已不在原位置。", path);
        throw new IOException("无法安全读取本地附件。");
    }
    public void Dispose() => Stream.Dispose();
    [StructLayout(LayoutKind.Explicit, Size = 256)]
    struct DarwinStat
    {
        [FieldOffset(0)] public uint Device;
        [FieldOffset(4)] public ushort Mode;
        [FieldOffset(8)] public ulong Inode;
        [FieldOffset(48)] public long ModifiedSeconds;
        [FieldOffset(56)] public long ModifiedNanoseconds;
        [FieldOffset(96)] public long Size;
    }
    [DllImport("libSystem.B.dylib", EntryPoint = "open", SetLastError = true)] static extern int OpenNative([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "openat", SetLastError = true)] static extern int OpenAt(int parent, [MarshalAs(UnmanagedType.LPUTF8Str)] string component, int flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat", SetLastError = true)] static extern int LStat([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat$INODE64", SetLastError = true)] static extern int LStatInode64([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat", SetLastError = true)] static extern int FStat(int descriptor, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat$INODE64", SetLastError = true)] static extern int FStatInode64(int descriptor, out DarwinStat value);
}
