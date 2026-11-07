using Microsoft.Data.Sqlite;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// Reads only already verified local copies. Native capture is a separate operation.
public sealed class MacArchiveImport(SqliteMessageStore store, string archive)
{
    // Inner service entry points: caller owns the lease and any full backup.
    internal async Task<WechatDbMessageImportResult> ImportMessagesUnderLeaseAsync(string account, bool full, IReadOnlyList<MacArchiveSourceFile> manifest, IProgress<string>? progress, CancellationToken token, MacImportStatistics statistics)
    {
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        using var snapshot = full ? MacArchiveSnapshot.Create(archive, account, manifest, token) : null;
        await RunCoreAsync((count, source) => progress?.Report($"已检查 {count:N0} 条 · {source}"), token, false, full, account, snapshot?.Root, statistics);
        return statistics.Result(true);
    }

    internal async Task<WechatContactImportResult> ImportContactsUnderLeaseAsync(string account, IReadOnlyList<MacArchiveSourceFile> manifest, IProgress<string>? progress, CancellationToken token)
    {
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        using var snapshot = MacArchiveSnapshot.Create(archive, account, manifest, token, contactsOnly: true);
        var source = Path.Combine(snapshot.Root, "accounts", account, "decrypted/contact/contact.db");
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        var directory = WechatContactImportService.ReadContactDirectory(source, token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        progress?.Report("正在写入联系人目录…");
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        var saved = await store.ReplaceWechatContactsAsync(directory.Contacts, directory.ChatRooms, directory.Members, "contact.db", token, usedCachedKey: true);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        await store.SaveDbNamesAsync(account, directory.Contacts, token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        await store.SaveDbProfilesAsync(account, directory.Contacts, directory.Members, token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        var friends = await store.SaveDbContactMetadataAsync(account, Path.Combine(archive, "accounts", account), directory.Contacts, token);
        return new(true, saved.ContactCount, saved.ChatRoomCount, saved.MemberCount, true, 0, null) { FriendCount = friends };
    }

    public Task<long> RunAsync(Action<long, string> progress, CancellationToken token) => RunAsync(progress, token, historyRescan: false);

    // History downloads may add local ids below an existing sync cursor. Explicit
    // rescans read the full source and report only newly inserted messages; normal
    // synchronization retains its existing scanned-row progress/count contract.
    public Task<long> RunAsync(Action<long, string> progress, CancellationToken token, bool historyRescan)
        => RunCoreAsync(progress, token, historyRescan, fullReparse: false, selectedAccount: null);

    public Task<long> RunForAccountAsync(string account, Action<long, string> progress, CancellationToken token)
        => RunCoreAsync(progress, token, historyRescan: false, fullReparse: false, selectedAccount: account);

    // Match the original importer: a verified full backup precedes source work;
    // only successful completion applies retention. Failures retain the backup
    // and all previously committed batches, without deleting saved history.
    public async Task<long> ReparseAsync(string account, Func<CancellationToken, Task<IReadOnlyList<MacArchiveSourceFile>>> refreshSource, Action<long, string> progress, CancellationToken token)
    {
        ValidateAccount(account);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        using var lease = await store.AcquireDbSyncLeaseWaitingAsync(null, token);
        progress(0, "正在备份并校验现有记录库…");
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        var backup = await store.BackupBeforeReparseAsync(token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        var manifest = await refreshSource(token);
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        using var snapshot = MacArchiveSnapshot.Create(archive, account, manifest, token);
        var count = await RunCoreAsync(progress, token, historyRescan: false, fullReparse: true, selectedAccount: account, snapshotRoot: snapshot.Root);
        await store.CompleteBackupAsync(backup, token);
        return count;
    }

    static void ValidateAccount(string account)
    {
        if (!Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,256}\z")) throw new ArgumentException("账号标识无效。");
    }

    async Task<long> RunCoreAsync(Action<long, string> progress, CancellationToken token, bool historyRescan, bool fullReparse, string? selectedAccount, string? snapshotRoot = null, MacImportStatistics? statistics = null)
    {
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
        SourcePathProtection.ProtectDirectory(archive);
        if (snapshotRoot is not null) SourcePathProtection.ProtectDirectory(snapshotRoot);
        long total = 0;
        var accountsRoot = Path.Combine(snapshotRoot ?? archive, "accounts");
        if (selectedAccount is not null) ValidateAccount(selectedAccount);
        if (!Directory.Exists(accountsRoot)) { if (selectedAccount is not null) throw new DirectoryNotFoundException("没有所选账号的已验证本地副本。"); return 0; }
        var accountRoots = selectedAccount is null ? Directory.EnumerateDirectories(accountsRoot) : new[] { Path.Combine(accountsRoot, selectedAccount) };
        foreach (var accountRoot in accountRoots)
        {
            PlaybackWorkCoordinator.Shared.Checkpoint(token);
            if (!Directory.Exists(accountRoot)) throw new DirectoryNotFoundException("没有所选账号的已验证本地副本。");
            var account = Path.GetFileName(accountRoot);
            int separator = account.LastIndexOf('_'); var self = separator >= 0 ? account[..separator] : account;
            var plain = Path.Combine(accountRoot, "decrypted");
            var contactsPath = Path.Combine(plain, "contact", "contact.db");
            var names = new Dictionary<string, string>(StringComparer.Ordinal);
            if (File.Exists(contactsPath))
            {
                PlaybackWorkCoordinator.Shared.Checkpoint(token);
                var directory = WechatContactImportService.ReadContactDirectory(contactsPath, token);
                PlaybackWorkCoordinator.Shared.Checkpoint(token);
                await store.SaveDbContactMetadataAsync(account, Path.Combine(archive, "accounts", account), directory.Contacts, token);
                PlaybackWorkCoordinator.Shared.Checkpoint(token);
                await store.SaveDbNamesAsync(account, directory.Contacts, token);
                PlaybackWorkCoordinator.Shared.Checkpoint(token);
                await store.SaveDbProfilesAsync(account, directory.Contacts, directory.Members, token);
                foreach (var contact in directory.Contacts)
                    names["Msg_" + Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes(contact.Username))).ToLowerInvariant()] = contact.Username;
            }
            var messageRoot = Path.Combine(plain, "message");
            if (!Directory.Exists(messageRoot)) { if (selectedAccount is not null) throw new DirectoryNotFoundException("没有所选账号的消息副本。"); continue; }
            var sources = Directory.EnumerateFiles(messageRoot, "*.db").Where(path => Regex.IsMatch(Path.GetFileName(path), @"^(biz_)?message_\d+\.db$")).Order(StringComparer.Ordinal).ToArray();
            if (selectedAccount is not null && sources.Length == 0) throw new InvalidDataException("没有所选账号的消息数据库。");
            using var writer = store.OpenDbWriteSession(account, token, 128);
            foreach (var path in sources)
            {
                PlaybackWorkCoordinator.Shared.Checkpoint(token);
                var source = Path.GetRelativePath(plain, path);
                var cursors = await store.GetDbSyncCursorsAsync(account, source, token);
                using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
                connection.Open();
                var directory = new Dictionary<long, string>();
                using (var command = connection.CreateCommand())
                {
                    command.CommandText = "SELECT rowid, CAST(user_name AS TEXT) FROM Name2Id";
                    using var rows = command.ExecuteReader();
                    while (rows.Read())
                    {
                        if (rows.IsDBNull(1)) continue;
                        string user = rows.GetString(1); directory[rows.GetInt64(0)] = user;
                        names["Msg_" + Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes(user))).ToLowerInvariant()] = user;
                    }
                }
                var tables = new List<string>();
                using (var command = connection.CreateCommand())
                {
                    command.CommandText = "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'";
                    using var rows = command.ExecuteReader();
                    while (rows.Read()) if (Regex.IsMatch(rows.GetString(0), "^Msg_[a-fA-F0-9]{32}$")) tables.Add(rows.GetString(0));
                }
                using var decoder = new WechatDbContentDecoder.DecodeSession();
                foreach (var table in tables)
                {
                    string chat = names.GetValueOrDefault(table, table[4..]);
                    long after = historyRescan || fullReparse ? -1 : Math.Max(-1, cursors.GetValueOrDefault(chat) - 500);
                    while (true)
                    {
                        PlaybackWorkCoordinator.Shared.Checkpoint(token);
                        using var command = connection.CreateCommand();
                        command.CommandText = $"SELECT server_id,server_seq,local_type,sort_seq,real_sender_id,create_time,message_content,WCDB_CT_message_content,packed_info_data,local_id FROM \"{table}\" WHERE local_id>$after ORDER BY local_id LIMIT 500";
                        command.Parameters.AddWithValue("$after", after);
                        var batch = new List<WechatDbMessage>();
                        using (var rows = command.ExecuteReader())
                        {
                            while (rows.Read())
                            {
                                token.ThrowIfCancellationRequested();
                                long id = rows.IsDBNull(0) ? 0 : rows.GetInt64(0), rawType = rows.GetInt64(2), local = rows.GetInt64(9);
                                // Keep locally generated/system rows too; original Windows reader discards zero IDs.
                                if (id == 0) id = LocalIdentity(source, table, local);
                                long sender = rows.IsDBNull(4) ? -1 : rows.GetInt64(4);
                                var kind = WechatDbTypeCodec.DecodeBaseType(rawType);
                                var content = rows.IsDBNull(6) ? [] : rows.GetValue(6) is byte[] bytes ? bytes : Encoding.UTF8.GetBytes(rows.GetString(6));
                                var decoded = WechatDbContentDecoder.DecodeContent(content, rows.IsDBNull(7) ? 0 : rows.GetInt64(7), decoder);
                                var parsed = WechatDbContentDecoder.ExtractText(decoded, kind, chat, directory.GetValueOrDefault(sender));
                                batch.Add(new WechatDbMessage(id, rows.IsDBNull(1) ? 0 : rows.GetInt64(1), kind, rawType, WechatDbTypeCodec.DecodeAppMsgSubType(rawType), rows.IsDBNull(3) ? 0 : rows.GetInt64(3), chat, sender, directory.GetValueOrDefault(sender), DateTimeOffset.FromUnixTimeSeconds(rows.GetInt64(5)), parsed.Status, parsed.PlainContent, parsed.RawContent, decoded.LongLength, rows.IsDBNull(8) ? 0 : rows.GetValue(8) is byte[] packed ? packed.LongLength : 0, source)
                                { AccountKey = account, LocalId = local, SelfUsername = self });
                                after = local;
                            }
                        }
                        if (batch.Count == 0) break;
                        PlaybackWorkCoordinator.Shared.Checkpoint(token);
                        statistics?.Read(batch);
                        var result = await writer.CommitAsync(batch, source, chat, after, token);
                        if (statistics is not null) { statistics.Inserted += result.Inserted; statistics.Updated += result.Updated; }
                        total += historyRescan ? result.Inserted : batch.Count;
                        progress(total, source);
                    }
                }
            }
        }
        return total;
    }
    internal static long LocalIdentity(string source, string table, long local) => -1 - (BitConverter.ToInt64(SHA256.HashData(Encoding.UTF8.GetBytes($"{source}\n{table}\n{local}"))) & long.MaxValue);
}
