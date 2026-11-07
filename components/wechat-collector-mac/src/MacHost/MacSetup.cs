using System.Text.Json;
using WechatUiCollector.Cli;
using WechatUiCollector.Configuration;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    bool setupOpen, setupBusy, setupStartupChecked;
    string setupSource = "", setupDirectory = "", setupSpace = "", setupError = "", setupDiscoveryRoot = "";
    MacSetupSource[] setupSources = [];
    readonly Dictionary<string, string> setupFolderRequests = new(StringComparer.Ordinal);
    Func<IWechatLocalImportProvider>? setupProviderFactory;
    object SetupState() => new { open = setupOpen, busy = setupBusy, source = setupSource,
        directory = setupDirectory.Length == 0 ? Path.GetDirectoryName(store.DatabasePath)! : setupDirectory,
        space = setupSpace, error = setupError, sources = setupSources.Select(source => new { path = source.Path, name = source.Name }).ToArray() };
    static bool ShouldOpenInitialSetup(string state, int importedAccounts) => state == "pending" && importedAccounts == 0;
    async Task MaybeOpenInitialSetupAsync(CancellationToken token)
    {
        if (setupStartupChecked) return;
        setupStartupChecked = true;
        if (Options.LocalChatSetupState != "pending") return;
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        // The existing chat list contains message accounts only. The original
        // reader also knows imported contact-only accounts; they are not first-run.
        if (!ShouldOpenInitialSetup(Options.LocalChatSetupState, (await reader.AccountsAsync(token)).Count)) return;
        await SetupCommandAsync("setupOpen", JsonSerializer.SerializeToElement(new { action = "setupOpen" }), token);
    }
    void QueueInitialSetupCheck()
    {
        _ = TrackShutdownTask(Task.Run(async () =>
        {
            try { await gate.WaitAsync(LifetimeToken); try { await MaybeOpenInitialSetupAsync(LifetimeToken); } finally { gate.Release(); } }
            catch (OperationCanceledException) { }
        }));
    }
    void UpdateSetupSpace()
    {
        try { setupSpace = $"可用 {new DriveInfo(setupDirectory).AvailableFreeSpace / 1073741824.0:0.0} GB"; }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException) { setupSpace = "空间信息暂不可用"; }
    }
    async Task OpenSetupAsync(CancellationToken token)
    {
        if (!syncWork.IsCompleted || !voiceWork.IsCompleted || exportBusy) throw new ArgumentException("请先等待当前处理完成，再更改导入位置。");
        setupOpen = true; setupBusy = true; setupError = ""; setupFolderRequests.Clear();
        setupDirectory = Path.GetDirectoryName(store.DatabasePath)!;
        setupDiscoveryRoot = string.IsNullOrWhiteSpace(Options.AttachmentSourceDirectory)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
            : ConfigurationLoader.ResolvePath(Options.AttachmentSourceDirectory, directory);
        token.ThrowIfCancellationRequested();
        setupSources = MacSetupSources.Discover(setupDiscoveryRoot, directory, archive);
        setupSource = setupSources.Length == 1 ? setupSources[0].Path : "";
        UpdateSetupSpace(); setupBusy = false;
        await Task.CompletedTask;
    }
    async Task SetupCommandAsync(string action, JsonElement command, CancellationToken token)
    {
        try
        {
            if (action == "selectedSetupFolder") await SetupFolderSelectedAsync(command, token);
            else
            {
                if (command.EnumerateObject().Any(property => property.Name != "action" && !(action == "setupAccount" && property.Name == "value"))) throw new ArgumentException("请通过本机目录选择框选择位置。");
                if (setupBusy) throw new ArgumentException("正在准备，请等当前操作完成。");
                if (action == "setupOpen") await OpenSetupAsync(token);
                else
                {
                    if (!setupOpen) throw new ArgumentException("请先打开聊天记录准备页面。");
                    setupError = "";
                    switch (action)
                    {
                        case "setupAccount":
                            var value = Text(command, "value");
                            if (!setupSources.Any(source => source.Path == value)) throw new ArgumentException("请选择已发现的微信账号。");
                            setupSource = value; break;
                        case "setupSource": case "setupDirectory":
                            string request = Guid.NewGuid().ToString("N"); setupFolderRequests.Clear(); setupFolderRequests.Add(request, action); setupBusy = true;
                            Post("chat", new { type = "macNative", command = "selectFolder", page = "chat", field = action, requestId = request, callbackAction = "selectedSetupFolder" }); break;
                        case "setupSkip":
                            SaveOptions(Options with { LocalChatSetupState = "skipped" }); setupOpen = false; setupStartupChecked = true; setupFolderRequests.Clear(); break;
                        case "setupStart": await SaveSetupAndStartAsync(token); break;
                        default: throw new ArgumentException("未知准备操作。");
                    }
                }
            }
        }
        catch (Exception error) when (error is not OperationCanceledException && error is not OutOfMemoryException)
        {
            // A forged callback must not consume the legitimate pending dialog.
            if (setupFolderRequests.Count == 0) setupBusy = false;
            setupError = error is ArgumentException ? error.Message : "未能保存或读取此位置，请检查目录权限和可用空间后重试。";
        }
        Post("chat", await ChatStateAsync(token));
    }
    Task SetupFolderSelectedAsync(JsonElement command, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (command.EnumerateObject().Any(property => property.Name is not ("action" or "requestId" or "field" or "path"))) throw new ArgumentException("目录选择回包无效。");
        string request = Text(command, "requestId"), field = Text(command, "field");
        if (!setupOpen || !setupFolderRequests.TryGetValue(request, out var expected) || field != expected) throw new ArgumentException("目录选择已过期，请重新选择。");
        setupFolderRequests.Remove(request); setupBusy = false;
        string path = Text(command, "path"); if (path.Length == 0) return Task.CompletedTask;
        path = MacSetupSources.Folder(path);
        if (field == "setupSource")
        {
            var sources = MacSetupSources.Discover(path, directory, archive);
            setupDiscoveryRoot = path; setupSources = sources; setupSource = sources.Length == 1 ? sources[0].Path : "";
            setupError = sources.Length == 0 ? "未找到微信账号。请选择 xwechat_files 文件夹或其中的账号文件夹。" : "";
        }
        else
        {
            string destination = SourcePathProtection.DatabasePath(Path.Combine(path, "records.db"));
            if (destination != store.DatabasePath) MacOutputProtection.Resolve(destination, store.DatabasePath, directory, archive);
            setupDirectory = Path.GetDirectoryName(destination)!; UpdateSetupSpace(); setupError = "";
        }
        return Task.CompletedTask;
    }
    async Task SaveSetupAndStartAsync(CancellationToken token)
    {
        if (ConnectionImportBlocked) throw new ArgumentException(ConnectionRecoveryMessage);
        if (setupSource.Length == 0 || !setupSources.Any(source => source.Path == setupSource)) throw new ArgumentException("请选择一个微信账号。");
        if (!MacSetupSources.Discover(setupDiscoveryRoot, directory, archive).Any(source => source.Path == setupSource)) throw new ArgumentException("微信目录已变化，请重新选择。");
        using (var verifier = new MacImportProvider(directory, archive))
            if (verifier.ResolveAccountRoot(setupSource) != setupSource) throw new ArgumentException("微信目录已变化，请重新选择。");
        string selectedSource = setupSource, selected = Path.GetFileName(setupSource);
        if (!syncWork.IsCompleted || !voiceWork.IsCompleted || voiceQueue.Count > 0 || exportBusy || DiagnosticsBusy || official?.Busy == true) throw new ArgumentException("请先等待当前处理完成，再开始导入。");
        string destination = SourcePathProtection.DatabasePath(Path.Combine(setupDirectory, "records.db"));
        if (destination != store.DatabasePath) MacOutputProtection.Resolve(destination, store.DatabasePath, directory, archive);
        if (!MacSetupSources.CachedCredentialsExist(archive, directory, selected)) { StartConnection(selectedSource, selected, destination); return; }
        var previousStore = store; var previousOptions = Options;
        var candidate = previousOptions with { AttachmentSourceDirectory = selectedSource, DatabasePath = destination, LocalChatSetupState = "pending" };
        setupBusy = true;
        try
        {
            if (destination == store.DatabasePath) SaveOptions(candidate);
            else await ChangeStorageAsync(destination, candidate.BackupRetentionCount, token, _ => SaveOptions(candidate));
        }
        catch { store = previousStore; savedOptions = previousOptions; throw; }
        setupFolderRequests.Clear(); setupStartupChecked = true;
        StartSetupImport(selectedSource, selected);
    }
    void StartSetupImport(string source, string selected)
    {
        if (ConnectionImportBlocked) throw new ArgumentException(ConnectionRecoveryMessage);
        var activeStore = store; string selectedArchive = archive;
        syncCancellation?.Dispose(); var cancellation = syncCancellation = OperationCancellation(); var token = cancellation.Token;
        syncOutcome = "notice"; syncStatus = "正在使用已缓存凭据导入本地记录…";
        syncWork = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                var provider = setupProviderFactory?.Invoke() ?? new MacImportProvider(directory, selectedArchive);
                try
                {
                    var progress = new InlineProgress<string>(text => { if (!token.IsCancellationRequested) Post("chat", new { type = "state", syncing = true, syncStatus, syncDetail = text }); });
                    var result = await new WechatMessageImportService(activeStore, localImportProvider: provider).ImportAsync(source, progress: progress, cancellationToken: token);
                    if (!result.Success) throw new IOException("缓存凭据导入未完成。");
                    await gate.WaitAsync(token);
                    try
                    {
                        if (!ReferenceEquals(store, activeStore)) throw new ArgumentException("记录保存位置已变化，请重新准备。");
                        SaveOptions(Options with { LocalChatSetupState = "completed" });
                        if (provider is MacImportProvider local) archive = local.ArchiveDirectory;
                        account = selected; chat = ""; selection++; version++; from = to = null; before = null; messageLimit = 100; messages = []; conversations = [];
                        hasEarlier = hasLater = false; followingLatest = true; InvalidatePersonChats();
                        setupOpen = false; setupBusy = false; setupError = ""; syncOutcome = "succeeded"; syncStatus = "当前账号的本地记录已更新。";
                        await ChatAsync("refresh", JsonSerializer.SerializeToElement(new { action = "refresh" }), token);
                    }
                    finally { gate.Release(); }
                }
                finally { (provider as IDisposable)?.Dispose(); }
            }
            catch (Exception error) when (error is not OutOfMemoryException)
            {
                await gate.WaitAsync();
                try { setupOpen = true; setupBusy = false; setupError = error is OperationCanceledException ? "导入已取消，已保存记录保留，可重试。" : "本地导入未完成，已保存记录保留；请检查缓存凭据与来源后重试。"; syncOutcome = error is OperationCanceledException ? "cancelled" : "failed"; syncStatus = setupError; }
                finally { gate.Release(); }
            }
            finally
            {
                await gate.WaitAsync();
                try { Post("chat", new { type = "state", setup = SetupState(), syncing = false, syncOutcome, syncStatus }); }
                finally { gate.Release(); }
            }
        }));
    }
}
