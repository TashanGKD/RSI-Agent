using System.Text.Json;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    readonly Dictionary<string, RecordIdentity> searchMatches = new();
    async Task RecordActionAsync(string action, JsonElement command, CancellationToken token)
    {
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        var value = Text(command, "value");
        switch (action)
        {
            case "peopleSearch":
                if (value.Length > 256) throw new ArgumentException("搜索内容最多 256 字。");
                int offset = int.TryParse(Text(command, "offset"), out var n) ? Math.Clamp(n, 0, 100000) : 0;
                bool friends = Text(command, "scope") != "all";
                var people = await reader.PeopleAsync(account, value, 101, token, friends, offset);
                PostReadResult(new { type = "people", account, requestId = Text(command, "requestId"), offset, hasMore = people.Count > 100, items = people.Take(100), query = value, scope = friends ? "friends" : "all" }); break;
            case "person": case "personRefresh":
                InvalidatePersonChats();
                if (string.IsNullOrWhiteSpace(value) || value.Length > 256) throw new ArgumentException("人物标识无效。");
                var person = await reader.PersonAsync(account, value, token); person["personas"] = await reader.PersonasAsync(account, value, token);
                token.ThrowIfCancellationRequested(); RegisterPersonChats(person);
                PostReadResult(new { type = "person", account, person, silent = action == "personRefresh" }); break;
            case "personChat": await OpenPersonChatAsync(value, token); break;
            case "chatMembers":
                string target = Text(command, "chat"), query = Text(command, "query"), cursor = Text(command, "cursor");
                var roster = await reader.ChatMembersAsync(account, target, query, 100, cursor.Length == 0 ? null : cursor, token);
                if (roster is null) throw new ArgumentException("该会话不是群聊或没有已保存记录。");
                PostReadResult(new { type = "chatMembers", account, chat = target, requestId = Text(command, "requestId"), chatName = roster.ChatName, memberCount = roster.MemberCount, rosterSynced = roster.Synced, items = roster.Items, nextCursor = roster.NextCursor, query }); break;
            case "messageSearch":
                await SearchKnowledgeAsync(command, token); break;
            case "literalMessageSearch":
                if (value.Length is 0 or > 500) throw new ArgumentException("请输入 1–500 字的消息关键词。");
                bool current = Text(command, "scope") == "current";
                var range = DateRange();
                var page = await reader.SearchAsync(new RecordSearch(account, current ? chat : null, value, From: range.From?.ToString("O"), ToExclusive: range.ToExclusive?.ToString("O"), ExactScan: true, IncludeTranscripts: true), 50, string.IsNullOrEmpty(Text(command, "cursor")) ? null : Text(command, "cursor"), token);
                var names = await store.GetDbNamesAsync(account, token);
                var items = page.Items.Select(row =>
                {
                    string id = row.GetValueOrDefault("messageId")?.ToString() ?? "";
                    if (id.Length > 0) searchMatches[id] = LocalRecordReader.ParseIdentity(id);
                    string resultChat = row.GetValueOrDefault("chatId")?.ToString() ?? "";
                    return new { messageId = id, chatName = names.GetValueOrDefault(resultChat, resultChat), senderName = row.GetValueOrDefault("senderName"), sentAt = row.GetValueOrDefault("sentAt"), content = row.GetValueOrDefault("content"), kind = "message", role = "body", transcriptMatch = row.GetValueOrDefault("transcriptMatch"), locator = (object?)null };
                }).ToArray();
                PostReadResult(new { type = "searchResults", account, items, cursor = page.NextCursor, query = value, scope = current ? "current" : "all", indexing = false }); break;
            case "searchResult":
                if (!searchMatches.TryGetValue(Text(command, "id"), out var identity))
                {
                    if (knowledgeMatches.TryGetValue(Text(command, "id"), out var content)) { await ContentDetailAsync(content.Source, content.Part, token); break; }
                    throw new ArgumentException("该搜索结果已过期，请重新搜索。");
                }
                if (identity.Account != account) throw new ArgumentException("该搜索结果属于其他账号。");
                var position = await store.FindDbMessagePositionAsync(account, identity.Chat, long.Parse(identity.ServerId), token);
                if (!position.Found) throw new ArgumentException("这条消息已不可用，请重新搜索。");
                ResetReadingPosition(); chat = identity.Chat; before = position.Before; selection++; from = to = null;
                messages = (await store.QueryDbMessagesAsync(account, chat, messageLimit, null, null, before, token)).Reverse().ToArray(); version++;
                hasEarlier = messages.Count == 100; hasLater = before is not null; followingLatest = before is null;
                scrollTarget = identity.ServerId;
                feedback = "已定位搜索结果，可向两端阅读上下文。"; break;
        }
    }
}
