using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

public sealed record MacArchiveSourceFile(string Path, long Bytes, string Sha256, string Identity, bool EmptyNonMessage = false)
{
    // Also used by synthetic fixtures; production manifests come from the worker.
    public static MacArchiveSourceFile Inspect(string archive, string account, string relative)
        => MacArchiveSnapshot.Inspect(archive, account, relative);
    public static MacArchiveSourceFile InspectEmpty(string archive, string account, string relative)
        => MacArchiveSnapshot.Inspect(archive, account, relative, true);
}

// One full operation owns these fixed CoW copies. No source is opened for writing.
internal sealed class MacArchiveSnapshot : IDisposable
{
    public string Root { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "wechat-reparse-snapshot-" + Guid.NewGuid().ToString("N"));
    static bool MessagePath(string path) => Regex.IsMatch(path, @"\Amessage/(biz_)?message_[0-9]+\.db\z");
    static bool CriticalPath(string path) => path == "contact/contact.db" || MessagePath(path);
    static bool EmptyPath(string path) => Regex.IsMatch(path, @"\Amessage/[A-Za-z0-9_.-]{1,128}\.db\z") && !CriticalPath(path);
    static bool KnownAuxiliary(string path) => Regex.IsMatch(path, @"\Amessage/media_[0-9]+\.db\z") || path is "message/message_resource.db" or "message/message_fts.db";

    public static MacArchiveSnapshot Create(string archive, string account, IReadOnlyList<MacArchiveSourceFile> files, CancellationToken token, bool contactsOnly = false)
    {
        if (!Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,256}\z") || files.Count < (contactsOnly ? 1 : 2) || files.Count > 512 ||
            files.Any(f => !(f.EmptyNonMessage ? EmptyPath(f.Path) : CriticalPath(f.Path)) || f.Bytes <= 0 || !Regex.IsMatch(f.Sha256, @"\A[a-f0-9]{64}\z") || !Regex.IsMatch(f.Identity, @"\A[0-9]+:[0-9]+:[0-9]+:[0-9]+\z")) ||
            files.Select(f => f.Path).Distinct(StringComparer.Ordinal).Count() != files.Count || !files.Any(f => f.Path == "contact/contact.db" && !f.EmptyNonMessage) || (contactsOnly ? files.Count != 1 : !files.Any(f => MessagePath(f.Path) && !f.EmptyNonMessage)))
            throw new IOException("全面重新解析的关键来源清单无效或不完整。");
        if (!contactsOnly) CompleteSet(archive, account, files);
        var snapshot = new MacArchiveSnapshot();
        try
        {
            ProtectedFileSystem.CreateDirectory(snapshot.Root);
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(snapshot.Root, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            foreach (var file in files)
            {
                token.ThrowIfCancellationRequested();
                var source = Source(archive, account, file.Path);
                Match(source, file);
                var target = System.IO.Path.Combine(snapshot.Root, "accounts", account, "decrypted", file.Path);
                ProtectedFileSystem.CreateDirectory(System.IO.Path.GetDirectoryName(target)!);
                MacArchiveClone.CopySnapshot(source, target);
                Match(source, file);
                if (new FileInfo(target).Length != file.Bytes || Hash(target, token) != file.Sha256)
                    throw new IOException("关键来源内容已变化，未开始全面重新解析。");
                if (file.EmptyNonMessage)
                {
                    using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = target, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
                    db.Open(); using var check = db.CreateCommand(); check.CommandText = "SELECT COUNT(*) FROM sqlite_schema";
                    if (Convert.ToInt64(check.ExecuteScalar(), CultureInfo.InvariantCulture) != 0) throw new IOException("未知消息来源已不再为空，未开始全面重新解析。");
                }

            }
            if (!contactsOnly) CompleteSet(archive, account, files);
            foreach (var file in files) Match(Source(archive, account, file.Path), file);
            return snapshot;
        }
        catch { snapshot.Dispose(); throw; }
    }
    static void CompleteSet(string archive, string account, IReadOnlyList<MacArchiveSourceFile> files)
    {
        var directory = Source(archive, account, "message");
        var actual = Directory.EnumerateFiles(directory, "*.db").Select(path => "message/" + System.IO.Path.GetFileName(path)).Where(MessagePath).Order(StringComparer.Ordinal);
        var expected = files.Select(f => f.Path).Where(MessagePath).Order(StringComparer.Ordinal);
        if (!actual.SequenceEqual(expected, StringComparer.Ordinal)) throw new IOException("消息分库集合已变化或清单不完整。");
        var unknown = Directory.EnumerateFiles(directory, "*.db").Select(path => "message/" + System.IO.Path.GetFileName(path)).Where(path => !MessagePath(path) && !KnownAuxiliary(path)).Order(StringComparer.Ordinal);
        if (!unknown.SequenceEqual(files.Where(f => f.EmptyNonMessage).Select(f => f.Path).Order(StringComparer.Ordinal), StringComparer.Ordinal)) throw new IOException("未知消息分库集合已变化，未开始全面重新解析。");
    }
    static string Source(string archive, string account, string relative)
    {
        var path = System.IO.Path.GetFullPath(archive);
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("来源不能是链接。");
        foreach (var part in new[] { "accounts", account, "decrypted" }.Concat(relative.Split('/')))
        {
            path = System.IO.Path.Combine(path, part);
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("关键来源不能是链接。");
        }
        return path;
    }
    internal static MacArchiveSourceFile Inspect(string archive, string account, string relative, bool emptyNonMessage = false)
    {
        if (!Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,256}\z") || !(emptyNonMessage ? EmptyPath(relative) : CriticalPath(relative))) throw new ArgumentException("来源标识无效。");
        var path = Source(archive, account, relative); var info = Stat(path);
        return new(relative, info.Size, Hash(path, default), Identity(info), emptyNonMessage);
    }
    static void Match(string path, MacArchiveSourceFile file)
    {
        if (new[] { "-wal", "-shm", "-journal" }.Any(suffix => File.Exists(path + suffix))) throw new IOException("关键来源存在未经验证的日志。");
        var info = Stat(path);
        if (info.Size != file.Bytes || Identity(info) != file.Identity) throw new IOException("关键来源身份已变化，未开始全面重新解析。");
    }
    static string Hash(string path, CancellationToken token)
    {
        using var file = File.OpenRead(path); using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[1024 * 1024]; int count;
        while ((count = file.Read(buffer)) > 0) { token.ThrowIfCancellationRequested(); hash.AppendData(buffer, 0, count); }
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }
    static string Identity(DarwinStat value) => string.Join(":", value.Device.ToString(CultureInfo.InvariantCulture), value.Inode.ToString(CultureInfo.InvariantCulture), value.Size.ToString(CultureInfo.InvariantCulture), checked(value.ModifiedSeconds * 1_000_000_000 + value.ModifiedNanoseconds).ToString(CultureInfo.InvariantCulture));
    static DarwinStat Stat(string path)
    {
        if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException("Mac archive identity requires macOS.");
        int result = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? LStatInode64(path, out var info) : LStat(path, out info);
        if (result != 0 || (info.Mode & 0xf000) != 0x8000 || info.Links != 1) throw new IOException("关键来源不是独立可读的普通副本。");
        return info;
    }
    [StructLayout(LayoutKind.Explicit, Size = 256)]
    struct DarwinStat
    {
        [FieldOffset(0)] public uint Device;
        [FieldOffset(4)] public ushort Mode;
        [FieldOffset(6)] public ushort Links;
        [FieldOffset(8)] public ulong Inode;
        [FieldOffset(48)] public long ModifiedSeconds;
        [FieldOffset(56)] public long ModifiedNanoseconds;
        [FieldOffset(96)] public long Size;
    }
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat", SetLastError = true)]
    static extern int LStat([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat$INODE64", SetLastError = true)]
    static extern int LStatInode64([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
}

public sealed record MacArchiveRefreshResult(string Summary, IReadOnlyList<MacArchiveSourceFile> Files, int FailedDatabaseCount = 0);
