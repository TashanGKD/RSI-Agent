using System.Collections.Concurrent;
using System.Text.Json;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    readonly ConcurrentDictionary<RecordIdentity, VoiceItemState> voiceItems = new();
    readonly Queue<(VoiceScope Scope, bool Force)> voiceQueue = new();
    readonly ConcurrentDictionary<RecordIdentity, VoiceItemUpdate> voiceFailures = new();
    CancellationTokenSource? voiceCancellation;
    Task voiceWork = Task.CompletedTask;
    VoiceModelState voiceModel = new("missing", "首次使用需要下载识别文件，之后可离线复用。", LocalTranscriber.ModelPath);
    string voiceStatus = "", voiceDetail = "";
    bool voiceSetup;
    async Task VoiceActionAsync(string action, JsonElement command, CancellationToken token)
    {
        switch (action)
        {
            case "cancelVoice":
                voiceCancellation?.Cancel();
                lock (voiceQueue) voiceQueue.Clear();
                CancelPendingVoiceItems();
                voiceStatus = "已停止，已完成文字保留；重新选择相同范围可继续。";
                Post("chat", await ChatStateAsync(token));
                return;
            case "voiceRuntime": LocalTranscriber.CheckEnvironment(); voiceStatus = "本地转写环境检查完成。"; break;
            case "voiceModel": StartVoiceWork(download: true); return;
            case "voiceCheck": voiceModel = await new VoiceModelManager().CheckAsync(token); voiceSetup = voiceModel.State != "ready"; voiceStatus = voiceModel.Description; break;
            case "voiceImport":
                Post("chat", new { type = "macNative", command = "importVoiceModel", page = "chat", requestId = "voiceModel" }); return;
            case "importVoiceModel":
                var path = Text(command, "path"); if (path.Length > 0) StartVoiceWork(import: path); return;
            case "deleteTranscript":
                var deleted = SelectedMessage(command); var deletedIdentity = VoiceIdentity(deleted);
                await store.DeleteTranscriptAsync(deletedIdentity, token); ReloadTranscript(deletedIdentity, null);
                EnsureVoiceRegistryScope(); voiceItems.TryRemove(deletedIdentity, out _); voiceFailures.TryRemove(deletedIdentity, out _); break;
            case "voiceFailureOpen": await OpenVoiceFailureAsync(Text(command, "id"), token); break;
            case "voiceBatch": case "transcribe":
                var range = DateRange(); var message = action == "transcribe" ? SelectedMessage(command) : null;
                if (chat.Length == 0 || message is not null && message.Type != WechatDbMessageType.Voice) throw new ArgumentException("请先选择包含语音的会话。");
                var scope = new VoiceScope(account, chat, message?.ServerId, message is null ? range.From?.ToString("O") : null, message is null ? range.ToExclusive?.ToString("O") : null);
                if (voiceQueue.Count >= 100) throw new ArgumentException("队列已满，请等当前任务完成后再添加。");
                lock (voiceQueue) if (!voiceQueue.Any(q => q.Scope == scope)) voiceQueue.Enqueue((scope, message?.Transcript is not null));
                StartVoiceWork(); return;
            case "voiceRetry":
                EnsureVoiceRegistryScope();
                lock (voiceQueue)
                    foreach (var failed in voiceFailures.Where(f => f.Key.Account == account))
                    {
                        if (voiceQueue.Count >= 100) break;
                        var retryScope = new VoiceScope(account, failed.Key.Chat, long.Parse(failed.Key.ServerId, System.Globalization.CultureInfo.InvariantCulture));
                        if (!voiceQueue.Any(queued => queued.Scope == retryScope)) voiceQueue.Enqueue((retryScope, true));
                    }
                StartVoiceWork(); return;
            default: throw new NotSupportedException("此语音操作尚未完成 Mac 适配。");
        }
        Post("chat", await ChatStateAsync(token));
    }
    void ReloadTranscript(RecordIdentity id, VoiceTranscript? transcript)
    {
        if (id.Account != account || id.Chat != chat) return;
        messages = messages.Select(m => VoiceIdentity(m) == id ? m with { Transcript = transcript?.Text, TranscriptVersion = transcript?.ModelVersion } : m).ToArray(); version++;
    }
    void StartVoiceWork(bool download = false, string? import = null)
    {
        if (!voiceWork.IsCompleted) return;
        voiceCancellation?.Dispose(); voiceCancellation = OperationCancellation(); var token = voiceCancellation.Token;
        var voiceStore = store; var voiceDatabase = voiceStore.DatabasePath;
        voiceWork = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                token.ThrowIfCancellationRequested(); LocalTranscriber.CheckEnvironment(); var manager = new VoiceModelManager();
                var progress = new Progress<string>(text => { voiceStatus = text; Post("chat", new { type = "state", voiceBusy = true, voiceStatus }); });
                if (download) await manager.EnsureAsync(progress, token);
                if (import is not null) await manager.ImportAsync(import, progress, token);
                voiceModel = await manager.CheckAsync(token); voiceSetup = voiceModel.State != "ready";
                if (voiceSetup) { voiceStatus = voiceModel.Description; return; }
                using var engine = new LocalTranscriber(LocalTranscriber.ModelPath);
                while (true)
                {
                    (VoiceScope Scope, bool Force) request;
                    lock (voiceQueue) { if (voiceQueue.Count == 0) break; request = voiceQueue.Dequeue(); }
                    var result = await voiceStore.TranscribeVoicesAsync(request.Scope, engine, async (message, ct) =>
                    {
                        (string Path, string Mime, string Url) audio;
                        try { audio = await LoadMediaAsync(message, ct); }
                        catch (MacAttachmentUnavailableException error) { throw new InvalidDataException(error.Message, error); }
                        catch (ArgumentException error) { throw new IOException(error.Message, error); }
                        if (audio.Mime != "audio/wav") throw new IOException("没有找到可验证的本地语音。");
                        return await File.ReadAllBytesAsync(audio.Path, ct);
                    }, 1000, request.Force, progress, token, all: true, update: async update =>
                    {
                        await gate.WaitAsync(token);
                        try { ApplyVoiceUpdate(update, voiceDatabase); if (voiceDatabase == store.DatabasePath && update.Transcript is not null) ReloadTranscript(VoiceIdentity(update.Message), update.Transcript); Post("chat", await ChatStateAsync(token)); }
                        finally { gate.Release(); }
                    });
                    voiceStatus = $"转写完成：新增 {result.Completed} 条，跳过 {result.Skipped} 条，未完成 {result.Failed} 条。";
                }
                if (voiceStatus.Length == 0) voiceStatus = "模型已就绪，可离线转文字。";
            }
            catch (OperationCanceledException) { voiceStatus = "转写已取消，已有文字保留。"; }
            catch (Exception error) when (error is not OutOfMemoryException) { voiceStatus = "语音转文字未完成，可检查模型后重试。"; voiceDetail = error.GetType().Name; }
            finally { Post("chat", new { type = "state", voiceBusy = false, voiceStatus, voiceDetail, voiceSetup, voiceModelState = voiceModel.State, voiceModelDescription = voiceModel.Description }); }
        }));
    }
}
