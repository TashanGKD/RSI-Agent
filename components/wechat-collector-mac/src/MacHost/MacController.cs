using System.Collections.Concurrent;
using System.Globalization;
using System.Text.Json;
using WechatUiCollector.Storage;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController(SqliteMessageStore store, string directory, string archive, IRecentLogSource? recentLogs = null)
{
    public static readonly HashSet<string> Pages = ["navigation", "chat", "export", "official", "settings", "health", "logs", "image"];
    readonly SemaphoreSlim gate = new(1);
    readonly ConcurrentDictionary<string, ConcurrentQueue<object>> events = new();
    readonly ConcurrentDictionary<string, bool> overflowReported = new();
    readonly Dictionary<string, JsonElement> chatStateFields = new(StringComparer.Ordinal);
    string selectedTab = "LocalChatsTab", account = "", chat = "", search = "", category = "all", feedback = "";
    string? from, to;
    string? scrollTarget, readingAnchor;
    double readingOffset;
    int selection, version, conversationLimit = 100, messageLimit = 100;
    bool hasEarlier, hasLater, hasNewMessages, followingLatest = true;
    WechatDbPageCursor? before;
    IReadOnlyList<WechatDbMessage> messages = [];
    IReadOnlyList<WechatDbConversation> conversations = [];
    public object[] Drain(string page)
    {
        if (!Pages.Contains(page)) return [];
        var result = new List<object>();
        if (events.TryGetValue(page, out var queue))
            lock (queue)
            {
                if (overflowReported.TryGetValue(page, out var reported) && !reported)
                {
                    result.Add(new { type = "macNative", command = "notice", code = "bridgeOverflow", text = "页面更新积压，部分操作结果未送达。请重新执行未完成的操作，或重新打开应用。" });
                    overflowReported[page] = true;
                }
                while (result.Count < 20 && queue.TryDequeue(out var value)) result.Add(value);
                // One visible failure per continuous backlog, even while producers
                // continue overflowing. A fully drained queue starts a new episode.
                if (queue.IsEmpty) overflowReported.TryRemove(page, out _);
            }
        return result.ToArray();
    }
    void Post(string page, object value)
    {
        if (LifetimeToken.IsCancellationRequested) return;
        var queue = events.GetOrAdd(page, _ => new());
        lock (queue)
        {
            if (page == "chat")
            {
                var state = JsonSerializer.SerializeToElement(value);
                if (Text(state, "type") == "state")
                {
                    // The original renderer only merges the two optional row lists.
                    // Background updates must retain all other required state fields.
                    foreach (var property in state.EnumerateObject())
                        if (property.Name is not ("messages" or "conversations")) chatStateFields[property.Name] = property.Value.Clone();
                    if (!chatStateFields.ContainsKey("accounts")) return;
                    var complete = new Dictionary<string, JsonElement>(chatStateFields, StringComparer.Ordinal);
                    foreach (var property in state.EnumerateObject())
                        if (property.Name is "messages" or "conversations") complete[property.Name] = property.Value.Clone();
                    if (queue.LastOrDefault() is Dictionary<string, JsonElement> pending)
                    {
                        // Consecutive progress snapshots supersede each other. Keep
                        // unsent row lists and an unsent one-time position instruction.
                        foreach (var name in new[] { "messages", "conversations" })
                            if (!complete.ContainsKey(name) && pending.TryGetValue(name, out var rows)) complete[name] = rows;
                        bool sameRows = new[] { "account", "conversation", "selection", "version" }.All(name => pending.TryGetValue(name, out var previous) && complete.TryGetValue(name, out var next) && previous.GetRawText() == next.GetRawText());
                        if (sameRows && (!state.TryGetProperty("scrollTarget", out var incomingTarget) || incomingTarget.ValueKind == JsonValueKind.Null) && pending.TryGetValue("scrollTarget", out var target) && target.ValueKind != JsonValueKind.Null)
                        {
                            complete["scrollTarget"] = target;
                            if (pending.TryGetValue("scrollOffset", out var offset)) complete["scrollOffset"] = offset;
                        }
                        var retained = queue.ToArray(); queue.Clear();
                        foreach (var earlier in retained.Take(retained.Length - 1)) queue.Enqueue(earlier);
                    }
                    value = complete;
                    // Positioning is a one-time instruction, not persistent metadata.
                    chatStateFields["scrollTarget"] = JsonSerializer.SerializeToElement((string?)null);
                    chatStateFields["scrollOffset"] = JsonSerializer.SerializeToElement(0);
                }
            }
            queue.Enqueue(value);
            while (queue.Count > 64)
            {
                queue.TryDequeue(out _);
                overflowReported.TryAdd(page, false);
            }
        }
    }
    static string Text(JsonElement value, string name) => value.TryGetProperty(name, out var item) ? item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : item.ToString() : "";
    public async Task<object[]> HandleAsync(string page, JsonElement command, CancellationToken token, bool drainEvents = true)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(token, LifetimeToken);
        token = lifetime.Token;
        string incomingAction = Text(command, "action");
        bool validQueryCommand = command.ValueKind == JsonValueKind.Object && incomingAction.Length is > 0 and <= 64 && !command.EnumerateObject().Any(p => p.Value.ValueKind == JsonValueKind.String && p.Value.GetString()!.Length > 16384);
        if (page == "chat" && validQueryCommand && incomingAction == "cancelQuery") { CancelReadQueries(); return drainEvents ? Drain(page) : []; }
        if (page == "chat" && validQueryCommand && IsReadQuery(incomingAction))
        {
            var pendingRead = EnqueueReadQueryAsync(command, token);
            if (drainEvents) { await pendingRead; return Drain(page); }
            return []; // HTTP acknowledges admission; the tracked pump publishes only via /events.
        }
        await gate.WaitAsync(token);
        try
        {
            string action = Text(command, "action");
            feedback = "";
            if (action.Length is 0 or > 64 || command.EnumerateObject().Any(p => p.Value.ValueKind == JsonValueKind.String && p.Value.GetString()!.Length > 16384)) throw new ArgumentException("页面请求超出允许范围。");
            if (page == "navigation")
            {
                if (action == "navigate")
                {
                    var id = Text(command, "id");
                    if (TabTuples.Any(tab => tab.id == id)) { selectedTab = id; Post(page, new { type = "macNavigation", id }); }
                }
                Post(page, new { type = "navigation", items = Tabs, selected = selectedTab });
            }
            else if (page == "chat") await ChatAsync(action, command, token);
            else if (page == "export") await ExportAsync(action, command, token);
            else if (page == "settings") await SettingsAsync(action, command, token);
            else if (page == "official") await OfficialAsync(command, token);
            else if (page == "image") await ImageAsync(command, token);
            else if (page == "health") await DiagnosticsActionAsync(page, Text(command, "action"), command, token);
            else throw new NotSupportedException("此功能的 Mac 适配尚未完成，未执行操作。");
        }
        catch (Exception error) when (error is not OperationCanceledException && error is not OutOfMemoryException)
        {
            feedback = error is NotSupportedException or ArgumentException ? error.Message : "读取未完成，请查看本地诊断后重试。";
            RuntimeEventSource.Emit(error is ArgumentException or NotSupportedException ? AppLogLevel.Warning : AppLogLevel.Error,
                "MAC_BRIDGE_COMMAND_FAILED", "MacController", "页面操作未完成。",
                new Dictionary<string, object?> { ["page"] = Pages.Contains(page) ? page : "unknown", ["errorType"] = error.GetType().Name });
            if (page == "chat") Post(page, await ChatStateAsync(token));
            else if (page == "export") Post(page, await ExportStateAsync(token));
            else Post(page, new { type = "macNative", command = "notice", text = feedback });
        }
        finally { gate.Release(); }
        return drainEvents ? Drain(page) : [];
    }
    static readonly (string id, string label)[] TabTuples = [("LocalChatsTab", "聊天记录"), ("HistoryExportTab", "历史导出"), ("OfficialAccountTab", "公众号文章"), ("SettingsTab", "设置")];
    static object[] Tabs => TabTuples.Select(tab => (object)new { tab.id, tab.label }).ToArray();
    async Task EnsureAccountAsync(CancellationToken token)
    {
        if (string.IsNullOrEmpty(account)) account = (await store.ListDbAccountsAsync(token)).FirstOrDefault() ?? "";
    }
    async Task ChatAsync(string action, JsonElement command, CancellationToken token)
    {
        if (action == "scroll") { UpdateReadingPosition(command); return; }
        await EnsureAccountAsync(token);
        var value = Text(command, "value");
        bool reloadMessages = false;
        switch (action)
        {
            case "ready": voiceModel = await new VoiceModelManager().CheckAsync(token); if (executingQuery is null) { EnsureKnowledgeIndex(); ConfigureAutoUpdate(Options.LocalChatAutoUpdateMinutes); } reloadMessages = committedQueryRows is null; if (!reloadMessages && !followingLatest) scrollTarget = readingAnchor; break;
            case "refresh": reloadMessages = followingLatest; break;
            case "account":
                if (!(await store.ListDbAccountsAsync(token)).Contains(value)) throw new ArgumentException("账号不存在。");
                InvalidatePersonChats();
                ResetReadingPosition(); account = value; chat = ""; selection++; before = null; messages = []; hasEarlier = hasLater = false; break;
            case "conversation":
                if (!conversations.Any(c => c.Username == value)) throw new ArgumentException("会话不存在。");
                ResetReadingPosition(); chat = value; selection++; before = null; messageLimit = 100; reloadMessages = true; break;
            case "search": search = value; conversationLimit = 100; break;
            case "category":
                if (!new[] { "all", "chats", "direct", "group", "business", "official", "subscription", "service", "folded", "system" }.Contains(value)) throw new ArgumentException("未知会话类别。");
                category = value; conversationLimit = 100; break;
            case "moreConversations": conversationLimit = Math.Min(10000, conversationLimit + 100); break;
            case "dates":
                from = Text(command, "from"); to = Text(command, "to"); DateRange(); ResetReadingPosition(); selection++; before = null; reloadMessages = true; break;
            case "earlier":
                if (Text(command, "selection") != selection.ToString()) return;
                await PageMessagesAsync(false, token); break;
            case "latest": ResetReadingPosition(); before = null; messageLimit = 100; reloadMessages = true; break;
            case "later":
                if (Text(command, "selection") != selection.ToString()) return;
                await PageMessagesAsync(true, token); break;
            case "thumbnailCancel": CancelThumbnail(command); return;
            case "cancelQuery": return;
            case "setupOpen": case "setupSkip": case "setupAccount": case "setupSource": case "setupDirectory": case "setupStart": case "selectedSetupFolder":
                await SetupCommandAsync(action, command, token); return;
            case "playback": Playback(Flag(command, "active")); return;
            case "settings":
                selectedTab = "SettingsTab"; Post("navigation", new { type = "macNavigation", id = selectedTab }); Post("navigation", new { type = "navigation", selected = selectedTab, items = Tabs }); break;
            case "copy": case "copyTime": case "copyTranscript": case "copyLink":
                var message = SelectedMessage(command); var card = WechatDbCard.Read(message);
                Post("chat", new { type = "macNative", command = "clipboard", text = action switch { "copyTime" => message.CreateTime.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss"), "copyTranscript" => message.Transcript ?? "", "copyLink" => card.Link?.AbsoluteUri ?? "", _ => message.PlainContent ?? card.Title ?? "" } }); break;
            case "peopleSearch": case "person": case "personRefresh": case "personChat": case "chatMembers": case "messageSearch": case "searchResult": await RecordActionAsync(action, command, token); break;
            case "contentMore":
                if (!int.TryParse(Text(command, "part"), out var part) || part < 0) throw new ArgumentException("内容页码无效。");
                await ContentDetailAsync(Text(command, "source"), part, token); break;
            case "sync" when setupOpen || Options.LocalChatSetupState == "skipped" || account.Length == 0:
                await SetupCommandAsync("setupOpen", JsonSerializer.SerializeToElement(new { action = "setupOpen" }), token); return;
            case "sync": case "reparse": case "repairSaved": case "cancelSync": case "auto": await SyncActionAsync(action, command, token); return;
            case "personaFolder": case "personaRefresh": case "personaCancel": case "personaNote": case "personaEvidence": case "personaExport": case "saveDocument": await PersonaActionAsync(action, command, token); break;
            case "forwarded": OpenForwarded(command); return;
            case "article": await ShowSavedArticleAsync(command, token); return;
            case "fileLocationAction": await FileLocationActionAsync(command, token); return;
            case "savedArticleAction": await SavedArticleActionAsync(command, token); return;
            case "forwardedAction": await ForwardedActionAsync(command, token); return;
            case "thumbnail": case "image": case "media": case "sticker": case "file": await MediaActionAsync(action, command, token); return;
            case "cancelVoice": case "voiceRuntime": case "voiceModel": case "voiceCheck": case "voiceImport": case "importVoiceModel": case "deleteTranscript": case "voiceBatch": case "transcribe": case "voiceRetry": case "voiceFailureOpen": await VoiceActionAsync(action, command, token); return;
            case "location":
                var location = WechatDbCard.Read(SelectedMessage(command)).Location;
                Post("chat", new { type = "macNative", command = "clipboard", text = string.Join("\n", new[] { location?.Name, location?.Address, location?.Coordinates }.Where(s => !string.IsNullOrEmpty(s))) }); break;
            case "quote":
                var quoted = SelectedMessage(command); var quote = WechatDbCard.Read(quoted).Quote;
                if (quote?.ServerId is null || !long.TryParse(quote.ServerId, out _)) { feedback = "引用未包含原消息标识，保留引用快照。"; break; }
                var quotePosition = await store.FindDbMessagePositionAsync(account, quoted.ConversationUsername, long.Parse(quote.ServerId), token);
                if (!quotePosition.Found) { feedback = "原消息尚未导入，引用快照仍可查看。"; break; }
                ResetReadingPosition(); from = to = null; before = quotePosition.Before; chat = quoted.ConversationUsername; selection++; reloadMessages = true; scrollTarget = quote.ServerId; feedback = "已定位引用的原消息"; break;
            case "link": case "bodyLink":
                var selected = SelectedMessage(command); string? link = action == "link" ? WechatDbCard.Read(selected).Link?.AbsoluteUri : Text(command, "url");
                if (link is null || action == "bodyLink" && selected.PlainContent?.Contains(link, StringComparison.Ordinal) != true || !Uri.TryCreate(link, UriKind.Absolute, out var uri) || uri.Scheme is not ("https" or "http")) throw new ArgumentException("链接无法验证。");
                Post("chat", new { type = "macNative", command = "openUrl", url = uri.AbsoluteUri }); break;
            case "fontError": throw new ArgumentException("界面字体加载失败，请重新打开程序。");
            default: throw new NotSupportedException("此功能的 Mac 适配尚未完成，未执行操作。");
        }
        conversations = await store.ListDbConversationsAsync(account, search, 0, token, category, conversationLimit);
        if (chat.Length == 0 && conversations.Count > 0) { chat = conversations[0].Username; selection++; reloadMessages = true; }
        if (reloadMessages && !string.IsNullOrEmpty(chat))
        {
            var range = DateRange();
            messages = (await store.QueryDbMessagesAsync(account, chat, messageLimit, range.From, range.ToExclusive, before, token)).Reverse().ToArray();
            hasEarlier = messages.Count == 100; hasLater = before is not null; followingLatest = before is null;
            hasNewMessages = false; version++;
        }
        else if (action == "refresh" && !followingLatest) await CheckNewMessagesAsync(token);
        PostReadResult(await ChatStateAsync(token));
    }
    async Task CheckNewMessagesAsync(CancellationToken token)
    {
        var range = DateRange();
        var latest = chat.Length == 0 ? null : (await store.QueryDbMessagesAsync(account, chat, 1, range.From, range.ToExclusive, null, token)).FirstOrDefault();
        hasNewMessages = latest is not null && (messages.Count == 0 || latest.SortSeq > messages[^1].SortSeq
            || latest.SortSeq == messages[^1].SortSeq && latest.ServerId > messages[^1].ServerId);
    }
    void ResetReadingPosition()
    {
        readingAnchor = scrollTarget = null; readingOffset = 0; followingLatest = true; hasNewMessages = false;
    }
    void UpdateReadingPosition(JsonElement command)
    {
        // This event comes from the original Web reader's debounced scroll
        // producer. Validate against the current in-memory page, without reads.
        if (!command.TryGetProperty("selection", out var selected) || selected.ValueKind != JsonValueKind.Number || !selected.TryGetInt32(out var revision) || revision != selection
            || !command.TryGetProperty("bottom", out var bottom) || bottom.ValueKind is not (JsonValueKind.True or JsonValueKind.False)
            || !command.TryGetProperty("anchor", out var anchor) || anchor.ValueKind != JsonValueKind.String
            || !messages.Any(message => message.ServerId.ToString(CultureInfo.InvariantCulture) == anchor.GetString())
            || !command.TryGetProperty("offset", out var offset) || offset.ValueKind != JsonValueKind.Number || !offset.TryGetDouble(out var pixels) || !double.IsFinite(pixels)) return;
        followingLatest = bottom.GetBoolean() && !hasLater;
        readingAnchor = anchor.GetString(); readingOffset = Math.Clamp(pixels, -10000, 10000);
        Post("chat", new { type = "state", followingLatest, scrollOffset = readingOffset });
    }
    (DateTimeOffset? From, DateTimeOffset? ToExclusive) DateRange() => WechatDbDateFilter.Resolve(ParseDate(from), ParseDate(to));
    static DateTime? ParseDate(string? value) => string.IsNullOrEmpty(value) ? null : DateTime.ParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture);
    WechatDbMessage SelectedMessage(JsonElement command)
    {
        if (Text(command, "version") != version.ToString() || !int.TryParse(Text(command, "index"), out var index) || index < 0 || index >= messages.Count) throw new ArgumentException("消息已更新，请重新选择。");
        return messages[index];
    }
    async Task<object> ChatStateAsync(CancellationToken token)
    {
        if (executingQuery is null) InvalidateFileLocations();
        if (executingQuery is null) CancelObsoleteThumbnails();
        var accounts = await store.ListDbAccountsAsync(token);
        var names = await store.GetDbNamesAsync(account, token);
        var info = await store.GetDbAccountInfoAsync(account, token);
        var self = info?.Username ?? (account.Contains('_') ? account[..account.LastIndexOf('_')] : account);
        string label = info?.DisplayName ?? "微信账号";
        var state = new
        {
            type = "state", setup = SetupState(),
            accounts = accounts.Select(key => new { key, label = key == account ? label : "微信账号" }), account, accountLabel = label,
            conversations = conversations.Select(c => new { id = c.Username, name = c.DisplayName, preview = c.Preview, avatar = AvatarUrl(account, c.AvatarHash), category = c.CategoryLabel, time = c.LocalLatest.ToString("MM-dd") }),
            conversation = chat, title = names.GetValueOrDefault(chat, chat.Length == 0 ? "选择一个会话" : chat), search, category, from, to, selection, version, query = queryBusy,
            phase = queryPhase, elapsed = 0, status = feedback, startupReady = true, readOutcome = queryOutcome.Length > 0 ? queryOutcome : accounts.Count == 0 ? "empty" : "succeeded", readFeedback = feedback,
            readScope = queryScope, sourcePending = false, syncOutcome, lastUpdated, preparationSteps = Array.Empty<string>(), migrationNotice = (string?)null,
            emptyHint = accounts.Count == 0 ? Options.LocalChatSetupState == "skipped" ? "准备好后，点击更新导入聊天记录。" : "本地记录尚未导入。" : "当前会话没有符合条件的消息。", syncing = !syncWork.IsCompleted, syncStatus, syncDetail, syncTooltip = syncDetail,
            voiceBusy = !voiceWork.IsCompleted, voiceStatus, voiceDetail, voiceSetup, voiceModelState = voiceModel.State, voiceModelDescription = voiceModel.Description, voiceModelPath = LocalTranscriber.ModelPath, voiceQueued = voiceQueue.Count, voiceScopeTitle = chat, voiceFailureCount = CurrentVoiceFailureCount, voiceFailures = VoiceFailuresState(names), voiceItems = VoiceItemsState(),
            autoMinutes, autoPaused, hasEarlier, hasLater, hasMoreConversations = conversations.Count >= conversationLimit, followingLatest, hasNewMessages, scrollTarget, scrollOffset = readingOffset,
            messages = messages.Select((m, index) => MacMessagePresentation.Row(m with { SelfUsername = self }, index > 0 ? messages[index - 1] with { SelfUsername = self } : null, names, index, chat.EndsWith("@chatroom"), AvatarUrl(account, m.AvatarHash))).ToArray()
        };
        if (executingQuery is null) RememberReadRows(state);
        scrollTarget = null; return state;
    }
    async Task PageMessagesAsync(bool newer, CancellationToken token)
    {
        if (messages.Count == 0 || newer && !hasLater || !newer && !hasEarlier) return;
        var anchor = newer ? messages[^1] : messages[0]; var range = DateRange();
        var page = await store.QueryDbMessagesAsync(account, chat, 100, range.From, range.ToExclusive, new WechatDbPageCursor(anchor.SortSeq, anchor.ServerId), token, newer);
        if (newer)
        {
            hasLater = page.Count == 100;
            var combined = messages.Concat(page).DistinctBy(m => m.ServerId).ToArray();
            hasEarlier |= combined.Length > 500; messages = combined.TakeLast(500).ToArray();
        }
        else
        {
            hasEarlier = page.Count == 100;
            var combined = page.Reverse().Concat(messages).DistinctBy(m => m.ServerId).ToArray();
            hasLater |= combined.Length > 500; messages = combined.Take(500).ToArray();
        }
        followingLatest = false; version++;
    }
}
