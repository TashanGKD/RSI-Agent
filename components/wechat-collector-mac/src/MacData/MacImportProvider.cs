using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;
using WechatUiCollector.Safety;

[assembly:System.Runtime.CompilerServices.InternalsVisibleTo("MacImportParity")]

namespace WechatCollector.Mac;

// Shared local-source adapter. Service callers own the DB lease and full backup.
public sealed partial class MacImportProvider : IWechatLocalImportProvider, IDisposable
{
    readonly string state, originalArchive, sources;
    readonly MacArchiveClone.Preparation? clonePreparation;
    readonly CancellationTokenSource lifetime = new();
    public string ArchiveDirectory => Path.Combine(state, "archive");
    public MacImportProvider(string stateDirectory, string? archive = null, string? sourceRoot = null)
        : this(stateDirectory,archive,sourceRoot,null) { }
    internal MacImportProvider(string stateDirectory,string? archive,string? sourceRoot,MacArchiveClone.Preparation? clonePreparation)
    {
        this.clonePreparation=clonePreparation;
        state = Path.GetFullPath(stateDirectory);
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        originalArchive = Path.GetFullPath(archive ?? Path.Combine(home, "Library/Application Support/LocalWeChatReader"));
        sources = Path.GetFullPath(sourceRoot ?? Path.Combine(home, "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"));
    }
    public string ResolveAccountRoot(string? accountRoot, string? filesRoot = null)
    {
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(accountRoot ?? filesRoot ?? sources));
        CheckComponents(root);
        if (!Directory.Exists(Path.Combine(root, "db_storage")))
        {
            var choices = Directory.EnumerateDirectories(root).Where(path => Directory.Exists(Path.Combine(path, "db_storage"))).ToArray();
            if (choices.Length != 1) throw new ArgumentException("需要明确选择唯一的微信账号来源目录。");
            root = choices[0];
        }
        CheckComponents(root); CheckComponents(Path.Combine(root, "db_storage"));
        if (!Regex.IsMatch(Path.GetFileName(root), @"\A[A-Za-z0-9_-]{1,256}\z")) throw new ArgumentException("微信账号目录标识无效。");
        SourcePathProtection.ProtectDirectory(root);
        return root;
    }
    public string? ResolveAccountRootForAccount(string account, string? accountRoot = null)
    {
        // The record account is a directory identifier, never a path fragment.
        if (account is null || !Regex.IsMatch(account, @"\A[A-Za-z0-9_-]{1,256}\z")) throw new ArgumentException("微信账号目录标识无效。");
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(accountRoot ?? sources));
        if (!Directory.Exists(root)) return null;
        CheckComponents(root);
        bool direct = Directory.Exists(Path.Combine(root, "db_storage"));
        if (direct && !string.Equals(Path.GetFileName(root), account, StringComparison.Ordinal)) return null;
        var parent = direct ? Path.GetDirectoryName(root) : root;
        if (parent is null) return null;
        // Enumerate the physical name: case-insensitive filesystems also accept aliases.
        var candidate = Directory.EnumerateDirectories(parent, account)
            .FirstOrDefault(path => string.Equals(Path.GetFileName(path), account, StringComparison.Ordinal));
        if (candidate is null || !Directory.Exists(Path.Combine(candidate, "db_storage"))) return null;
        return ResolveAccountRoot(candidate);
    }
    static void CheckComponents(string path)
    {
        for (string? current = path; current is not null; current = Path.GetDirectoryName(current))
        {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) == 0) continue;
            if (current is "/var" or "/tmp" or "/etc" && new DirectoryInfo(current).ResolveLinkTarget(true)?.FullName == "/private" + current) continue;
            throw new IOException("账号来源目录不能包含链接。");
        }
    }
    public async Task<WechatDbMessageImportResult> ImportMessagesAsync(SqliteMessageStore store, string? accountRoot, string? filesRoot, IProgress<string>? progress, CancellationToken token, bool full)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, lifetime.Token);
        var clock = Stopwatch.StartNew();
        var statistics = new MacImportStatistics();
        int failedSources = 0;
        try
        {
            Checkpoint(progress, linked.Token);
            var root = ResolveAccountRoot(accountRoot, filesRoot); var account = Path.GetFileName(root);
            Checkpoint(progress, linked.Token);
            var archive = await PrepareArchiveAsync(linked.Token);
            Checkpoint(progress, linked.Token);
            var refreshed = await MacImportWorker.RefreshAsync(archive, account, Path.GetDirectoryName(root)!, full, false, progress, linked.Token);
            failedSources = refreshed.FailedDatabaseCount;
            var result = await new MacArchiveImport(store, archive).ImportMessagesUnderLeaseAsync(account, full, refreshed.Files, progress, linked.Token, statistics);
            if (result.Success) await ImportOptionalAvatarsAsync(store, archive, account, progress, linked.Token);
            if (refreshed.Summary.Length > 0) progress?.Report(refreshed.Summary);
            return result with { ElapsedMilliseconds = clock.ElapsedMilliseconds,
                Success = result.Success && refreshed.FailedDatabaseCount == 0,
                FailedDatabaseCount = refreshed.FailedDatabaseCount,
                Error = refreshed.FailedDatabaseCount == 0 ? result.Error : "部分消息来源未完成读取；已提交记录保留，请检查来源后重试。" };
        }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or ArgumentException or SqliteException or System.Text.Json.JsonException or System.ComponentModel.Win32Exception)
        {
            return statistics.Result(false, clock.ElapsedMilliseconds) with { FailedDatabaseCount = Math.Max(1, failedSources) };
        }
    }
    public async Task<WechatContactImportResult> ImportContactsAsync(SqliteMessageStore store, string? accountRoot, IProgress<string>? progress, CancellationToken token, bool full)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, lifetime.Token);
        var clock = Stopwatch.StartNew();
        try
        {
            Checkpoint(progress, linked.Token);
            var root = ResolveAccountRoot(accountRoot); var account = Path.GetFileName(root);
            Checkpoint(progress, linked.Token);
            var archive = await PrepareArchiveAsync(linked.Token);
            Checkpoint(progress, linked.Token);
            var refreshed = await MacImportWorker.RefreshAsync(archive, account, Path.GetDirectoryName(root)!, false, true, progress, linked.Token);
            var result = await new MacArchiveImport(store, archive).ImportContactsUnderLeaseAsync(account, refreshed.Files, progress, linked.Token);
            if (result.Success) await ImportOptionalAvatarsAsync(store, archive, account, progress, linked.Token);
            return result with { ElapsedMilliseconds = clock.ElapsedMilliseconds };
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException or SqliteException or System.Text.Json.JsonException or System.ComponentModel.Win32Exception)
        { return new(false, 0, 0, 0, true, clock.ElapsedMilliseconds, "联系人来源未完成导入；已保存记录保留。"); }
    }
    Task<string> PrepareArchiveAsync(CancellationToken token) => clonePreparation is null
        ? MacArchiveClone.PrepareAsync(originalArchive,state,token)
        : MacArchiveClone.PrepareAsync(originalArchive,state,token,clonePreparation);
    static async Task ImportOptionalAvatarsAsync(SqliteMessageStore store, string archive, string account, IProgress<string>? progress, CancellationToken token)
    {
        try { await MacAvatarImport.ImportAsync(store, archive, account, token); }
        catch (IOException) { progress?.Report("本地头像尚未完成读取，已保存头像保留；联系人与消息导入继续。"); }
    }
    static void Checkpoint(IProgress<string>? progress, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (PlaybackWorkCoordinator.Shared.IsActive) progress?.Report("播放期间已暂停后台更新，播放结束后继续…");
        PlaybackWorkCoordinator.Shared.Checkpoint(token);
    }
    public void Dispose() { lifetime.Cancel(); if (localMedia.IsValueCreated) localMedia.Value.Dispose(); }
}
