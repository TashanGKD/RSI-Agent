using System.Text.Json;
using WechatUiCollector.Storage;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    Task knowledgeWork = Task.CompletedTask;
    CancellationTokenSource? knowledgeCancellation;
    readonly Dictionary<string, KnowledgeHit> knowledgeMatches = new();
    void EnsureKnowledgeIndex()
    {
        if (!knowledgeWork.IsCompleted) return;
        knowledgeCancellation?.Dispose(); knowledgeCancellation = OperationCancellation(); var token = knowledgeCancellation.Token; string database = store.DatabasePath;
        knowledgeWork = TrackShutdownTask(Task.Run(async () =>
        {
            try
            {
                var index = new KnowledgeStore(database);
                while (await index.HasWorkAsync(token))
                    await index.UpdateAsync(Path.Combine(Path.GetDirectoryName(database)!, "article-bodies"), 500, token);
            }
            catch (OperationCanceledException) { }
            catch (Exception error) when (error is not OutOfMemoryException) { File.AppendAllText(Path.Combine(directory, "bridge-errors.log"), $"{DateTimeOffset.Now:O} content-index {error.GetType().Name}\n"); }
        }, token));
    }
    async Task SearchKnowledgeAsync(JsonElement command, CancellationToken token)
    {
        string text = Text(command, "value"), cursor = Text(command, "cursor"); bool current = Text(command, "scope") == "current";
        if (text.Length is 0 or > 500 || current && chat.Length == 0) throw new ArgumentException("请输入 1–500 字的关键词，并选择搜索范围。");
        EnsureKnowledgeIndex(); var dates = DateRange(); var index = new KnowledgeStore(store.DatabasePath);
        var page = await index.SearchAsync(new KnowledgeQuery(account, text, current ? chat : null, From: dates.From?.ToString("O"), To: dates.ToExclusive?.ToString("O"), IncludeLibrary: !current), 50, cursor.Length == 0 ? null : cursor, token);
        var names = await store.GetDbNamesAsync(account, token);
        var items = page.Items.Select(hit =>
        {
            string id = hit.Source + "#" + hit.Part; knowledgeMatches[id] = hit;
            if (hit.Kind == "message") { var identity = JsonSerializer.Deserialize<string[]>(hit.Source)!; searchMatches[id] = new RecordIdentity(identity[1], identity[2], identity[3]); }
            return new { messageId = id, chatName = hit.Kind == "message" ? names.GetValueOrDefault(hit.Chat, hit.Chat) : hit.Title, senderName = hit.Sender, sentAt = hit.Time, content = hit.Text, kind = hit.Kind, role = hit.Role, transcriptMatch = hit.Role == "transcript" ? 1 : 0, locator = hit.Locator };
        }).ToArray();
        PostReadResult(new { type = "searchResults", account, items, cursor = page.NextCursor, query = text, scope = current ? "current" : "all", coverage = page.Coverage, indexing = !knowledgeWork.IsCompleted });
        feedback = page.Coverage.BaselineComplete && page.Coverage.Pending == 0 ? $"找到 {items.Length} 项内容。" : $"正在建立内容索引，当前找到 {items.Length} 项。";
    }
    async Task ContentDetailAsync(string source, int part, CancellationToken token)
    {
        if (!knowledgeMatches.Values.Any(hit => hit.Source == source)) throw new ArgumentException("该搜索结果已过期，请重新搜索。");
        PostReadResult(new { type = "contentDetail", data = await new KnowledgeStore(store.DatabasePath).ReadAsync(source, account, part, 5, token) });
    }
}
