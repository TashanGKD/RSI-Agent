using System.Text.Json;
using System.Text.RegularExpressions;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    MacForwardFiles? forwardedFiles;
    MacForwardSession? forwardedFilesSession;
    int forwardedFilesRevision;
    CancellationTokenSource? forwardedFileCancellation;
    readonly SemaphoreSlim forwardedFileGate = new(1);
    static string ForwardSourceRoot(WechatUiCollector.WechatDb.WechatDbMessage owner)
    {
        if (!Regex.IsMatch(owner.AccountKey, "^[A-Za-z0-9_-]{1,256}$", RegexOptions.CultureInvariant)) throw new ArgumentException("转发父消息账号无效。");
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files", owner.AccountKey);
    }
    void CancelForwardedFiles()
    {
        forwardedFileCancellation?.Cancel(); forwardedFiles = null; forwardedFilesSession = null;
        forwardedSession?.SetFileCandidates(null);
    }
    void StartForwardedFileSearch(MacForwardSession current, int revision, int[] itemPath)
    {
        if (account != current.Owner.AccountKey) throw new ArgumentException("当前账号已切换，请重新打开聊天记录。");
        forwardedFileCancellation?.Cancel();
        var files = forwardedFiles = new MacForwardFiles(current.Owner, itemPath, ForwardSourceRoot(current.Owner));
        forwardedFilesSession = current; forwardedFilesRevision = revision;
        var cancellation = forwardedFileCancellation = OperationCancellation(TimeSpan.FromSeconds(90));
        current.SetStatus("正在查找本地文件…"); current.SetFileCandidates(files.State());
        _ = TrackShutdownTask(RunForwardedFileWorkAsync(current, revision, files, cancellation, async () => { await files.SearchAsync(cancellation.Token); return null; }));
    }
    void ForwardedFileAction(MacForwardSession current, int revision, JsonElement command)
    {
        var files = forwardedFiles;
        if (files is null || !ReferenceEquals(forwardedFilesSession, current) || forwardedFilesRevision != revision || Text(command, "candidateToken") != files.Token)
            throw new ArgumentException("文件候选已过期，请重新查找。");
        switch (Text(command, "operation"))
        {
            case "fileClose": CancelForwardedFiles(); break;
            case "fileRetry": StartForwardedFileSearch(current, revision, files.ItemPath); break;
            case "fileReveal":
                if (account != files.Owner.AccountKey) throw new ArgumentException("当前账号已切换，请重新打开聊天记录。");
                forwardedFileCancellation?.Cancel();
                var cancellation = forwardedFileCancellation = OperationCancellation(TimeSpan.FromSeconds(90));
                int index = Number(command, "candidateIndex", -1); string candidateToken = Text(command, "candidateToken");
                files.SetStatus("正在核对…", true); current.SetFileCandidates(files.State());
                _ = TrackShutdownTask(RunForwardedFileWorkAsync(current, revision, files, cancellation, async () => await files.VerifyAsync(candidateToken, index, cancellation.Token)));
                break;
        }
    }
    async Task RunForwardedFileWorkAsync(MacForwardSession current, int revision, MacForwardFiles files, CancellationTokenSource cancellation, Func<Task<string?>> operation)
    {
        string? reveal = null, failure = null;
        bool acquired = false;
        try { await forwardedFileGate.WaitAsync(cancellation.Token); acquired = true; reveal = await operation(); }
        catch (OperationCanceledException) { failure = "本地文件查找或核对已取消，请重试。"; }
        catch (Exception error) when (error is not OutOfMemoryException) { failure = error is ArgumentException ? error.Message : "暂时无法读取本地文件，请检查目录权限后重试。"; }
        finally { if (acquired) forwardedFileGate.Release(); }
        await gate.WaitAsync();
        try
        {
            if (!ReferenceEquals(forwardedSession, current) || current.Revision != revision || !ReferenceEquals(forwardedFiles, files) || !ReferenceEquals(forwardedFileCancellation, cancellation)) return;
            if (failure is not null) files.SetStatus(failure);
            else if (reveal is not null)
            {
                if (account != files.Owner.AccountKey) files.SetStatus("当前账号已切换，未打开文件夹。");
                else { Post("chat", new { type = "macNative", command = "reveal", path = reveal }); files.SetStatus(files.RevealedStatus); }
            }
            current.SetFileCandidates(files.State()); current.SetStatus("本地文件候选已更新。"); PublishForwarded();
        }
        finally
        {
            if (ReferenceEquals(forwardedFileCancellation, cancellation)) forwardedFileCancellation = null;
            gate.Release(); cancellation.Dispose();
        }
    }
}
