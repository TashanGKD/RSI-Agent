using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using Microsoft.Win32.SafeHandles;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// Optional, account-scoped source. Callers own the store's import lease and
// handle an unavailable avatar copy without failing the contact/message import.
public static class MacAvatarImport
{
    const int MaximumAvatarBytes = 1_048_576;
    const string Unavailable = "本地头像副本未完成校验；已保存头像保留，可稍后重试。";
    public static async Task<int> ImportAsync(SqliteMessageStore store, string archive, string account, CancellationToken token)
    {
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException("本地头像副本读取需要 macOS。");
        if (!Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,256}\z")) throw new ArgumentException("头像账号标识无效。");
        string? temporary = null;
        try
        {
            var source = CanonicalSystemAliases(Path.Combine(Path.GetFullPath(archive), "accounts", account, "decrypted", "head_image", "head_image.db"));
            if (!CheckSourceComponents(source)) return 0;
            SourcePathProtection.ProtectFile(source);
            CheckNoJournals(source);
            var before = LStatRegular(source);
            // NOFOLLOW_ANY rejects a parent component swapped after our checks;
            // NONBLOCK prevents a replacement FIFO/device from blocking open.
            // Darwin rejects combining NOFOLLOW_ANY with NOFOLLOW (EINVAL).
            // ANY already covers the leaf as well as all parent components.
            int descriptor = Open(source, 0x20000000 | 0x00000004);
            if (descriptor < 0) throw new IOException(Unavailable);
            using var handle = new SafeFileHandle((IntPtr)descriptor, ownsHandle: true);
            using var original = new FileStream(handle, FileAccess.Read);
            Match(before, FStatRegular(descriptor));
            var expectedHash = await SHA256.HashDataAsync(original, token);
            Match(before, FStatRegular(descriptor)); Match(before, LStatRegular(source));

            PlaybackWorkCoordinator.Shared.Checkpoint(token);
            temporary = CanonicalSystemAliases(Path.Combine(Path.GetTempPath(), "wechat-avatar-snapshot-" + Guid.NewGuid().ToString("N")));
            ProtectedFileSystem.CreateDirectory(temporary);
            File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            string snapshot = Path.Combine(temporary, "head_image.db");
            // Clone from the validated descriptor, never reopen a changing source
            // pathname. On a filesystem without CoW, copy that same descriptor.
            if (CloneDescriptor(descriptor, -2, snapshot, 0) != 0)
            {
                original.Position = 0;
                await using var destination = new FileStream(snapshot, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                File.SetUnixFileMode(snapshot, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                await original.CopyToAsync(destination, token);
            }
            File.SetUnixFileMode(snapshot, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            var snapshotIdentity = LStatRegular(snapshot);
            if (snapshotIdentity.Size != before.Size) throw new IOException(Unavailable);
            await using (var fixedFile = File.OpenRead(snapshot))
                if (!expectedHash.SequenceEqual(await SHA256.HashDataAsync(fixedFile, token))) throw new IOException(Unavailable);
            Match(before, FStatRegular(descriptor)); Match(before, LStatRegular(source)); CheckNoJournals(source);

            PlaybackWorkCoordinator.Shared.Checkpoint(token);
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = snapshot, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            await db.OpenAsync(token);
            using var readCancellation = SqliteReadCancellation.Attach(db, token);
            using (var integrity = db.CreateCommand())
            {
                integrity.CommandText = "PRAGMA quick_check";
                using var rows = await integrity.ExecuteReaderAsync(token);
                if (!await rows.ReadAsync(token) || rows.GetString(0) != "ok" || await rows.ReadAsync(token)) throw new IOException(Unavailable);
            }
            Match(snapshotIdentity, LStatRegular(snapshot));
            using var query = db.CreateCommand();
            query.CommandText = "SELECT username,image_buffer FROM head_image WHERE length(image_buffer) BETWEEN 1 AND 1048576";
            using var avatars = await query.ExecuteReaderAsync(token);
            var batch = new List<(string User, byte[] Bytes)>(100); int accepted = 0;
            while (await avatars.ReadAsync(token))
            {
                token.ThrowIfCancellationRequested();
                if (avatars.IsDBNull(0) || avatars.GetString(0).Length > 256 || avatars.GetValue(1) is not byte[] bytes || bytes.Length is < 1 or > MaximumAvatarBytes) continue;
                // SaveAvatarsAsync remains the authority for MIME, hash, size and
                // UPSERT semantics. Unsupported formats are ignored there.
                batch.Add((avatars.GetString(0), bytes));
                if (batch.Count == 100) { accepted += await SaveBatchAsync(store, account, batch, token); batch.Clear(); }
            }
            if (batch.Count > 0) accepted += await SaveBatchAsync(store, account, batch, token);
            return accepted;
        }
        catch (SqliteException error) when (token.IsCancellationRequested) { throw new OperationCanceledException("头像读取已取消。", error, token); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or SqliteException)
        { throw new IOException(Unavailable, error); }
        finally { if (temporary is not null && Directory.Exists(temporary)) Directory.Delete(temporary, recursive: true); }
    }
    static async Task<int> SaveBatchAsync(SqliteMessageStore store, string account, List<(string User, byte[] Bytes)> batch, CancellationToken token)
    {
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        await store.SaveAvatarsAsync(account, batch, token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        // Only count values the original saver accepted, via its original hash/
        // read API; no duplicate image-type parser is introduced by this adapter.
        int accepted = 0;
        foreach (var (_, bytes) in batch)
        {
            token.ThrowIfCancellationRequested();
            if (await store.ReadAvatarAsync(account, Convert.ToHexString(SHA256.HashData(bytes)), token) is not null) accepted++;
        }
        return accepted;
    }
    static string CanonicalSystemAliases(string path)
    {
        foreach (var alias in new[] { "/var", "/tmp", "/etc" })
            if (path == alias || path.StartsWith(alias + "/", StringComparison.Ordinal)) return "/private" + path;
        return path;
    }
    static bool CheckSourceComponents(string source)
    {
        string current = "/";
        foreach (var part in source.Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            if (TryLStat(current, out var value) != 0)
            {
                if (Marshal.GetLastWin32Error() == 2) return false;
                throw new IOException(Unavailable);
            }
            if ((value.Mode & 0xf000) == 0xa000) throw new IOException(Unavailable);
            if (current != source && (value.Mode & 0xf000) != 0x4000) throw new IOException(Unavailable);
        }
        return true;
    }
    static void CheckNoJournals(string path)
    {
        foreach (var suffix in new[] { "-wal", "-shm", "-journal" })
            if (TryLStat(path + suffix, out _) == 0 || Marshal.GetLastWin32Error() != 2) throw new IOException(Unavailable);
    }
    static DarwinStat LStatRegular(string path)
    {
        if (TryLStat(path, out var value) != 0) throw new IOException(Unavailable);
        return Regular(value);
    }
    static DarwinStat FStatRegular(int descriptor)
    {
        int status = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? FStatInode64(descriptor, out var value) : FStat(descriptor, out value);
        if (status != 0) throw new IOException(Unavailable);
        return Regular(value);
    }
    static DarwinStat Regular(DarwinStat value)
    {
        if ((value.Mode & 0xf000) != 0x8000 || value.Links != 1 || value.Size <= 0) throw new IOException(Unavailable);
        return value;
    }
    static int TryLStat(string path, out DarwinStat value) => RuntimeInformation.ProcessArchitecture == Architecture.X64 ? LStatInode64(path, out value) : LStat(path, out value);
    static void Match(DarwinStat first, DarwinStat second)
    {
        if (first.Device != second.Device || first.Inode != second.Inode || first.Size != second.Size || first.ModifiedSeconds != second.ModifiedSeconds || first.ModifiedNanoseconds != second.ModifiedNanoseconds) throw new IOException(Unavailable);
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
    [DllImport("libSystem.B.dylib", EntryPoint = "open", SetLastError = true)] static extern int Open([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "fclonefileat", SetLastError = true)] static extern int CloneDescriptor(int source, int directory, [MarshalAs(UnmanagedType.LPUTF8Str)] string destination, uint flags);
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat", SetLastError = true)] static extern int LStat([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "lstat$INODE64", SetLastError = true)] static extern int LStatInode64([MarshalAs(UnmanagedType.LPUTF8Str)] string path, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat", SetLastError = true)] static extern int FStat(int descriptor, out DarwinStat value);
    [DllImport("libSystem.B.dylib", EntryPoint = "fstat$INODE64", SetLastError = true)] static extern int FStatInode64(int descriptor, out DarwinStat value);
}
