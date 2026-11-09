using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using WechatUiCollector.Configuration;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    sealed class FileLocationBinding(SqliteMessageStore database, string source, WechatDbMessage owner, MacFileLocation files)
    {
        public SqliteMessageStore Database = database;
        public string Source = source;
        public WechatDbMessage Owner = owner;
        public MacFileLocation Files = files;
        public CancellationTokenSource? Work;
        public string? RevealToken;
    }
    readonly Dictionary<string, FileLocationBinding> fileLocationWindows = new(StringComparer.Ordinal);
    readonly SemaphoreSlim fileLocationGate = new(1);
    string FileLocationRoot(string ownerAccount)
    {
        if (!Regex.IsMatch(ownerAccount, "^[A-Za-z0-9_-]{1,256}$", RegexOptions.CultureInvariant)) throw new ArgumentException("文件所属账号无效。");
        var configured = Options.AttachmentSourceDirectory;
        var source = string.IsNullOrWhiteSpace(configured)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
            : ConfigurationLoader.ResolvePath(configured, directory);
        source = Path.GetFullPath(source);
        if (source.StartsWith("/var/", StringComparison.Ordinal) || source.StartsWith("/tmp/", StringComparison.Ordinal)) source = "/private" + source;
        return Path.GetFileName(Path.TrimEndingDirectorySeparator(source)) == ownerAccount ? source : Path.Combine(source, ownerAccount);
    }
    void InvalidateFileLocations()
    {
        foreach (var pair in fileLocationWindows.ToArray())
            if (!FileLocationScopeCurrent(pair.Value)) CloseFileLocation(pair.Key);
    }
    bool FileLocationScopeCurrent(FileLocationBinding binding) => ReferenceEquals(binding.Database, store) && binding.Owner.AccountKey == account && binding.Owner.ConversationUsername == chat && binding.Source == FileLocationRoot(account);
    void CloseFileLocation(string request)
    {
        if (!fileLocationWindows.Remove(request, out var binding)) return;
        if (binding.Work is { } work) TryCancel(work);
        Post("chat", new { type = "macNative", command = "closeFileLocation", requestId = request });
    }
    async Task ValidateFileLocationAsync(FileLocationBinding binding, CancellationToken token)
    {
        if (!FileLocationScopeCurrent(binding)) throw new ArgumentException("文件窗口的账号、会话或保存位置已变化，请重新打开。");
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        var owner = binding.Owner;
        WechatDbMessage current;
        try { current = await reader.MessageAsync(new RecordIdentity(owner.AccountKey, owner.ConversationUsername, owner.ServerId.ToString(CultureInfo.InvariantCulture)), token); }
        catch (KeyNotFoundException) { throw new ArgumentException("原文件消息已不可用，请重新打开。"); }
        if (current != owner) throw new ArgumentException("原文件消息已变化，请重新打开。");
    }
    async Task ShowFileLocationAsync(WechatDbMessage selected, CancellationToken token)
    {
        InvalidateFileLocations();
        if (selected.AccountKey != account || selected.ConversationUsername != chat) throw new ArgumentException("当前账号或会话已变化，请重新选择。");
        if (fileLocationWindows.Count >= 16) throw new ArgumentException("请先关闭一些文件窗口，再打开新窗口。");
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        var owner = await reader.MessageAsync(new RecordIdentity(selected.AccountKey, selected.ConversationUsername, selected.ServerId.ToString(CultureInfo.InvariantCulture)), token);
        if (owner.LocalId != selected.LocalId || owner.TypeRaw != selected.TypeRaw || owner.RawContent != selected.RawContent || owner.CreateTime != selected.CreateTime) throw new ArgumentException("原文件消息已变化，请重新选择。");
        var card = WechatDbCard.Read(owner);
        if (card.FileName is null) throw new ArgumentException("这条消息没有可查找的文件名。");
        var source = FileLocationRoot(owner.AccountKey);
        var files = new MacFileLocation(source, card.FileName, card.FileSize, card.FileHash, owner.CreateTime);
        var request = Guid.NewGuid().ToString("N"); var binding = new FileLocationBinding(store, source, owner, files);
        fileLocationWindows.Add(request, binding); StartFileLocationWork(request, binding, false);
    }
    void PublishFileLocation(string request, FileLocationBinding binding) => Post("chat", new { type = "macNative", command = "fileLocation", requestId = request, state = binding.Files.State() });
    async Task FileLocationActionAsync(JsonElement command, CancellationToken token)
    {
        var request = Text(command, "requestId");
        if (!fileLocationWindows.TryGetValue(request, out var binding)) throw new ArgumentException("文件窗口已关闭或过期，请重新打开。");
        try
        {
            if (command.EnumerateObject().Any(p => p.Name is not ("action" or "requestId" or "operation" or "candidateToken" or "candidateIndex" or "revealToken" or "succeeded"))) throw new ArgumentException("文件窗口操作不能指定文件路径。");
            var operation = Text(command, "operation");
            if (operation == "close") { CloseFileLocation(request); return; }
            try { await ValidateFileLocationAsync(binding, token); }
            catch { CloseFileLocation(request); throw; }
            if (Text(command, "candidateToken") != binding.Files.Token) throw new ArgumentException("文件候选已过期，请重新查找。");
            if (operation == "revealResult")
            {
                if (binding.RevealToken is null || Text(command, "revealToken") != binding.RevealToken) throw new ArgumentException("文件夹操作已过期。");
                binding.RevealToken = null;
                binding.Files.SetStatus(Flag(command, "succeeded") ? binding.Files.RevealedStatus : "无法打开文件夹，请重试。"); PublishFileLocation(request, binding); return;
            }
            if (binding.Work is not null || binding.RevealToken is not null) throw new ArgumentException("正在查找或核对文件，请稍候。");
            if (operation == "retry") StartFileLocationWork(request, binding, false);
            else if (operation == "reveal") StartFileLocationWork(request, binding, true, Number(command, "candidateIndex", -1));
            else throw new ArgumentException("未知文件窗口操作。");
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            if (fileLocationWindows.ContainsKey(request))
            {
                binding.Files.SetStatus(error is ArgumentException ? error.Message : error is OperationCanceledException ? "本地文件查找或核对已取消，请重试。" : "暂时无法读取本地文件，请检查目录权限后重试。", binding.Work is not null || binding.RevealToken is not null);
                PublishFileLocation(request, binding);
            }
        }
    }
    static string FileLocationFailure(Exception error, bool verify) => error switch
    {
        ArgumentException => error.Message,
        OperationCanceledException => "本地文件查找或核对已取消，请重试。",
        FileNotFoundException or DirectoryNotFoundException when verify => "文件已不在原位置，请重新查找。",
        UnauthorizedAccessException when verify => "没有文件访问权限，请检查权限后重试。",
        _ when verify => "暂时无法读取文件，请稍后重试。",
        _ => "无法读取附件目录，请检查目录权限后重新查找。"
    };
    void StartFileLocationWork(string request, FileLocationBinding binding, bool verify, int index = -1)
    {
        var cancellation = binding.Work = OperationCancellation(TimeSpan.FromSeconds(90));
        binding.Files.SetStatus(verify ? "正在核对…" : "正在查找本地文件…", true); PublishFileLocation(request, binding);
        var candidateToken = binding.Files.Token;
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            string? path = null, failure = null; bool acquired = false;
            try
            {
                await fileLocationGate.WaitAsync(cancellation.Token); acquired = true;
                if (verify) path = await binding.Files.VerifyAsync(candidateToken, index, cancellation.Token);
                else await binding.Files.SearchAsync(cancellation.Token);
            }
            catch (Exception error) when (error is not OutOfMemoryException)
            { failure = FileLocationFailure(error, verify); }
            finally { if (acquired) fileLocationGate.Release(); }
            await gate.WaitAsync();
            try
            {
                if (!fileLocationWindows.TryGetValue(request, out var current) || !ReferenceEquals(current, binding) || !ReferenceEquals(binding.Work, cancellation)) return;
                try { await ValidateFileLocationAsync(binding, cancellation.Token); }
                catch (OperationCanceledException) { failure = "本地文件查找或核对已取消，请重试。"; path = null; }
                catch (Exception error) when (error is not OutOfMemoryException) { CloseFileLocation(request); return; }
                if (failure is not null) binding.Files.SetStatus(failure);
                else if (path is not null)
                {
                    binding.RevealToken = Guid.NewGuid().ToString("N");
                    PublishFileLocation(request, binding);
                    Post("chat", new { type = "macNative", command = "fileLocationReveal", requestId = request, candidateToken = binding.Files.Token, candidateIndex = index, revealToken = binding.RevealToken, path }); return;
                }
                PublishFileLocation(request, binding);
            }
            finally { if (ReferenceEquals(binding.Work, cancellation)) binding.Work = null; gate.Release(); cancellation.Dispose(); }
        }));
    }
}
