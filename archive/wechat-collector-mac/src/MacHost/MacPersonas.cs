using System.Text.Json;
using System.Text;
using WechatUiCollector.Storage;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    FileSystemWatcher? personaWatcher;
    CancellationTokenSource? personaCancellation;
    readonly Dictionary<string, string> pendingDocuments = new();
    async Task PersonaActionAsync(string action, JsonElement command, CancellationToken token)
    {
        switch (action)
        {
            case "personaCancel": personaCancellation?.Cancel(); return;
            case "personaFolder":
                var folder = PersonaFolder.DirectoryFor(store.DatabasePath, account); ProtectedFileSystem.CreateDirectory(folder);
                Post("chat", new { type = "macNative", command = "openFolder", path = folder }); await RefreshPersonasAsync(token); break;
            case "personaRefresh": await RefreshPersonasAsync(token); break;
            case "personaNote":
                if (!int.TryParse(Text(command, "revision"), out var revision)) throw new ArgumentException("画像版本无效。");
                await store.SavePersonaNoteAsync(account, Text(command, "person"), Text(command, "chat"), revision, Text(command, "note"), token);
                Post("chat", new { type = "personaStatus", account, result = new { phase = "imported", message = "人工修订已保存，文件更新后仍会保留。" } });
                using (var person = JsonDocument.Parse(JsonSerializer.Serialize(new { value = Text(command, "person") }))) await RecordActionAsync("personRefresh", person.RootElement, token); break;
            case "personaEvidence":
                await using (var reader = new LocalRecordReader(store.DatabasePath))
                {
                    await reader.OpenAsync(token); string person = Text(command, "person"), sourceChat = Text(command, "chat"), id = Text(command, "id");
                    if (!(await reader.PersonasAsync(account, person, token)).Any(p => p.Document.ChatId == sourceChat && p.Document.Observations.Any(o => o.Evidence.Any(e => e.ServerId == id)))) throw new ArgumentException("这条依据不属于当前画像。");
                    var identity = new RecordIdentity(account, sourceChat, id); var messageId = LocalRecordReader.MessageId(identity); searchMatches[messageId] = identity;
                    using var selected = JsonDocument.Parse(JsonSerializer.Serialize(new { id = messageId })); await RecordActionAsync("searchResult", selected.RootElement, token);
                }
                break;
            case "personaExport":
                await using (var reader = new LocalRecordReader(store.DatabasePath))
                {
                    await reader.OpenAsync(token);
                    var saved = (await reader.PersonasAsync(account, Text(command, "person"), token)).SingleOrDefault(p => p.Document.ChatId == Text(command, "chat")) ?? throw new ArgumentException("画像不存在，请重新打开联系人。");
                    string requestId = Guid.NewGuid().ToString("N"); pendingDocuments[requestId] = PersonaYaml.Export(saved.Document);
                    Post("chat", new { type = "macNative", command = "saveDocument", page = "chat", requestId, filename = "person-persona.yaml", title = "导出本地画像（包含身份及证据 ID）" });
                }
                break;
            case "saveDocument":
                if (!pendingDocuments.Remove(Text(command, "requestId"), out var text)) throw new ArgumentException("文件选择已过期，请重试。");
                string path = Text(command, "path"); if (path.Length == 0) return;
                path = SafeUserOutput(path); string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
                try { await ProtectedFileSystem.WriteAllTextAsync(temporary, text, new UTF8Encoding(false), token); token.ThrowIfCancellationRequested(); ProtectedFileSystem.Move(temporary, path, overwrite: true); }
                finally { CleanupUserTemporary(temporary); }
                Post("chat", new { type = "personaStatus", account, result = new { phase = "done", message = "已导出原分析画像，本地人工修订单独保留。" } }); break;
        }
    }
    async Task RefreshPersonasAsync(CancellationToken token)
    {
        var result = await new PersonaFolder(store.DatabasePath).RefreshAsync(account, token);
        personaWatcher?.Dispose();
        var watcher = new FileSystemWatcher(result.Folder) { IncludeSubdirectories = true, NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName | NotifyFilters.Size | NotifyFilters.LastWrite };
        watcher.Changed += SchedulePersonaRefresh; watcher.Created += SchedulePersonaRefresh; watcher.Deleted += SchedulePersonaRefresh; watcher.Renamed += SchedulePersonaRefresh; watcher.EnableRaisingEvents = true; personaWatcher = watcher;
        Post("chat", new { type = "personaStatus", account, result = new { phase = "synced", folder = result.Folder, count = result.FileCount, changed = result.Changed, errors = result.Errors, message = result.Errors.Count > 0 ? "部分文件需要处理，已保留上次有效画像。" : "文件保存后自动更新" } });
    }
    void SchedulePersonaRefresh(object sender, FileSystemEventArgs eventArgs)
    {
        personaCancellation?.Cancel(); personaCancellation?.Dispose(); personaCancellation = OperationCancellation(); var token = personaCancellation.Token; string current = account;
        personaWork = TrackShutdownTask(Task.Run(async () =>
        {
            try { await Task.Delay(600, token); await gate.WaitAsync(token); try { if (current == account) await RefreshPersonasAsync(token); } finally { gate.Release(); } }
            catch (OperationCanceledException) { }
            catch (Exception error) when (error is not OutOfMemoryException) { Post("chat", new { type = "personaStatus", account = current, result = new { phase = "failed", message = "画像文件读取未完成，已保留上次有效版本。" } }); }
        }, token));
    }
}
