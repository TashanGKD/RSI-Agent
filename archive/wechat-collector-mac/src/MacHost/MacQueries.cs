using System.Diagnostics;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    sealed class QueryTicket(JsonElement command, CancellationTokenSource cancellation, long generation)
    {
        public readonly JsonElement Command = command.Clone();
        public readonly CancellationTokenSource Cancellation = cancellation;
        public readonly long Generation = generation;
        public readonly TaskCompletionSource Finished = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public readonly List<object> Events = [];
        public bool Invalid;
        public string Account = "";
    }
    readonly object queryLock = new();
    readonly Queue<QueryTicket> pendingQueries = new();
    QueryTicket? activeQuery, executingQuery;
    long queryGeneration;
    bool queryPumpRunning, queryBusy;
    string queryOutcome = "", queryPhase = "", queryScope = "本地已保存记录";
    long queryStarted;
    JsonElement? committedQueryRows, committedQueryConversations;
    string committedQueryAccount = "";
    static bool IsReadQuery(string action) => action is "ready" or "refresh" or "account" or "conversation" or "search" or "category" or "moreConversations"
        or "dates" or "earlier" or "latest" or "later" or "peopleSearch" or "person" or "personRefresh" or "personChat" or "chatMembers" or "messageSearch" or "searchResult" or "contentMore";
    static bool SupersedesQueries(string action) => action is not ("earlier" or "later" or "moreConversations" or "contentMore");
    static string QueryScope(string action) => action switch
    {
        "search" or "category" => "conversations", "moreConversations" => "conversationsMore",
        "earlier" => "earlier", "later" => "later", "messageSearch" => "search", _ => "messages"
    };
    // Only the admission/cancellation registry uses queryLock; it never awaits
    // the main gate or SQLite. Invalidating a ticket precedes asynchronous Cancel.
    void CancelReadQueries()
    {
        lock (queryLock)
        {
            queryGeneration++;
            if (activeQuery is { } active) { active.Invalid = true; _ = active.Cancellation.CancelAsync(); }
            while (pendingQueries.TryDequeue(out var pending))
            {
                pending.Invalid = true; _ = pending.Cancellation.CancelAsync(); PublishQueryFailure(pending, "已取消读取，已保存记录不受影响。"); pending.Finished.TrySetResult(); pending.Cancellation.Dispose();
            }
        }
    }
    Task EnqueueReadQueryAsync(JsonElement command, CancellationToken token)
    {
        lock (queryLock)
        {
            string action = Text(command, "action");
            if (SupersedesQueries(action)) CancelReadQueries();
            if (pendingQueries.Count >= 4)
            {
                Post("chat", new { type = "state", status = "读取队列已满，请等当前读取完成后重试。", readFeedback = "读取队列已满，请等当前读取完成后重试。" });
                return Task.CompletedTask;
            }
            var next = new QueryTicket(command, CancellationTokenSource.CreateLinkedTokenSource(token, LifetimeToken), queryGeneration) { Account = committedQueryAccount };
            pendingQueries.Enqueue(next);
            if (!queryPumpRunning)
            {
                queryPumpRunning = true;
                _ = TrackShutdownTask(Task.Run(RunReadQueriesAsync));
            }
            return next.Finished.Task;
        }
    }
    bool CurrentQuery(QueryTicket ticket) { lock (queryLock) return !ticket.Invalid && ticket.Generation == queryGeneration && !ticket.Cancellation.IsCancellationRequested; }
    async Task RunReadQueriesAsync()
    {
        while (true)
        {
            QueryTicket ticket;
            lock (queryLock)
            {
                if (!pendingQueries.TryDequeue(out ticket!)) { activeQuery = null; queryPumpRunning = false; return; }
                activeQuery = ticket;
            }
            bool entered = false;
            try
            {
                await gate.WaitAsync(ticket.Cancellation.Token); entered = true;
                if (!CurrentQuery(ticket)) continue;
                executingQuery = ticket; queryBusy = true; queryOutcome = "running"; queryScope = QueryScope(Text(ticket.Command, "action"));
                queryPhase = "正在读取已保存记录…"; queryStarted = Stopwatch.GetTimestamp();
                PublishQueryStatus();
                var original = CaptureReadState();
                ticket.Account = original.Account;
                try
                {
                    feedback = "";
                    await ChatAsync(Text(ticket.Command, "action"), ticket.Command, ticket.Cancellation.Token);
                    lock (queryLock)
                    {
                        if (!CurrentQuery(ticket)) throw new OperationCanceledException(ticket.Cancellation.Token);
                        queryBusy = false; queryOutcome = "succeeded"; queryPhase = "";
                        InvalidateFileLocations();
                        foreach (var value in ticket.Events) PublishReadResult(value);
                        CancelObsoleteThumbnails();
                        if (Text(ticket.Command, "action") == "ready") { EnsureKnowledgeIndex(); ConfigureAutoUpdate(Options.LocalChatAutoUpdateMinutes); QueueInitialSetupCheck(); }
                    }
                }
                catch (Exception error) when (error is not OutOfMemoryException)
                {
                    RestoreReadState(original); ticket.Events.Clear();
                    bool cancelled = !CurrentQuery(ticket) && error is OperationCanceledException or SqliteException;
                    // A provider may finish despite cancellation. Its result is
                    // still invalid; no draft rows or authorization maps escape.
                    cancelled |= !CurrentQuery(ticket);
                    queryBusy = false; queryOutcome = cancelled ? "cancelled" : "failed"; queryPhase = "";
                    feedback = cancelled ? "已取消读取，已保存记录不受影响。" : error is ArgumentException ? error.Message : "读取记录失败，请检查保存位置后重试。";
                    PublishQueryFailure(ticket, feedback);
                    PublishQueryStatus();
                }
            }
            catch (OperationCanceledException)
            {
                // The ticket may be waiting behind a mutation, before it owns
                // any read fields. Its frontend request still needs a terminal.
                PublishQueryFailure(ticket, "已取消读取，已保存记录不受影响。");
            }
            finally
            {
                if (entered) { executingQuery = null; gate.Release(); }
                lock (queryLock) { if (ReferenceEquals(activeQuery, ticket)) activeQuery = null; ticket.Cancellation.Dispose(); ticket.Finished.TrySetResult(); }
            }
        }
    }
    void PublishQueryStatus()
    {
        if (committedQueryRows is null)
            Post("chat", new { type = "state", accounts = Array.Empty<object>(), account, accountLabel = "微信账号", conversation = chat,
                title = "选择一个会话", messages = Array.Empty<object>(), conversations = Array.Empty<object>(), search, category, from, to, selection, version,
                setup = new { open = false, busy = false }, startupReady = false, followingLatest, hasNewMessages, hasEarlier, hasLater, hasMoreConversations = false,
                voiceItems = new Dictionary<string, object>(), voiceFailures = Array.Empty<object>(), query = queryBusy, readOutcome = queryOutcome,
                readScope = queryScope, phase = queryPhase, elapsed = 0, status = feedback, readFeedback = feedback, readScopeLabel = "本地已保存记录" });
        // Post merges this into the last committed full state, preserving rows.
        var status = JsonSerializer.SerializeToElement(new { type = "state", query = queryBusy, readOutcome = queryOutcome, readScope = queryScope,
            phase = queryPhase, elapsed = queryBusy ? (int)Stopwatch.GetElapsedTime(queryStarted).TotalSeconds : 0,
            status = feedback, readFeedback = feedback, scrollOffset = readingOffset, hasNewMessages });
        var fields = status.EnumerateObject().ToDictionary(property => property.Name, property => property.Value.Clone());
        if (committedQueryRows is { } rows) fields["messages"] = rows;
        if (committedQueryConversations is { } chats) fields["conversations"] = chats;
        Post("chat", fields);
    }
    void PostReadResult(object value)
    {
        if (executingQuery is { } ticket) ticket.Events.Add(value); else Post("chat", value);
    }
    void PublishQueryFailure(QueryTicket ticket, string error)
    {
        string action = Text(ticket.Command, "action");
        if (action == "messageSearch")
            Post("chat", new { type = "searchResults", account = ticket.Account, query = Text(ticket.Command, "value"), scope = Text(ticket.Command, "scope") == "current" ? "current" : "all", error });
        else if (action == "peopleSearch")
            Post("chat", new { type = "people", account = ticket.Account, requestId = Text(ticket.Command, "requestId"), query = Text(ticket.Command, "value"), scope = Text(ticket.Command, "scope") == "all" ? "all" : "friends", error });
        else if (action == "chatMembers")
            Post("chat", new { type = "chatMembers", account = ticket.Account, chat = Text(ticket.Command, "chat"), requestId = Text(ticket.Command, "requestId"), query = Text(ticket.Command, "query"), error });
    }
    void PublishReadResult(object value)
    {
        var element = JsonSerializer.SerializeToElement(value);
        if (Text(element, "type") != "state") { Post("chat", value); return; }
        var fields = element.EnumerateObject().ToDictionary(property => property.Name, property => property.Value.Clone());
        fields["query"] = JsonSerializer.SerializeToElement(false); fields["phase"] = JsonSerializer.SerializeToElement("");
        fields["elapsed"] = JsonSerializer.SerializeToElement(0); fields["readOutcome"] = JsonSerializer.SerializeToElement(queryOutcome);
        RememberReadRows(element);
        Post("chat", fields);
    }
    void RememberReadRows(object value)
    {
        var state = value is JsonElement element ? element : JsonSerializer.SerializeToElement(value);
        if (state.TryGetProperty("messages", out var rows)) committedQueryRows = rows.Clone();
        if (state.TryGetProperty("conversations", out var chats)) committedQueryConversations = chats.Clone();
        if (state.TryGetProperty("account", out var selected)) committedQueryAccount = selected.GetString() ?? "";
    }
    // A compact transaction for this controller's existing read fields. The gate
    // keeps drafts private; only query-specific events are buffered. Background
    // sync/voice/media progress keeps its original independent Post path.
    sealed record ReadState(string Account, string Chat, string Search, string Category, string Feedback, string? From, string? To, string? Scroll, string? ReadingAnchor, double ReadingOffset,
        int Selection, int Version, int ConversationLimit, int MessageLimit, bool Earlier, bool Later, bool Latest, bool NewMessages, WechatDbPageCursor? Before,
        IReadOnlyList<WechatDbMessage> Messages, IReadOnlyList<WechatDbConversation> Conversations,
        Dictionary<string, RecordIdentity> SearchMatches, Dictionary<string, KnowledgeHit> KnowledgeMatches,
        Dictionary<string, string> PersonChats, string? PersonAccount, string? PersonDatabase, VoiceModelState VoiceModel);
    ReadState CaptureReadState() => new(account, chat, search, category, feedback, from, to, scrollTarget, readingAnchor, readingOffset, selection, version, conversationLimit, messageLimit,
        hasEarlier, hasLater, followingLatest, hasNewMessages, before, messages, conversations, new(searchMatches), new(knowledgeMatches), new(personChats), personChatsAccount, personChatsDatabase, voiceModel);
    void RestoreReadState(ReadState state)
    {
        account = state.Account; chat = state.Chat; search = state.Search; category = state.Category; feedback = state.Feedback; from = state.From; to = state.To; scrollTarget = state.Scroll; readingAnchor = state.ReadingAnchor; readingOffset = state.ReadingOffset;
        selection = state.Selection; version = state.Version; conversationLimit = state.ConversationLimit; messageLimit = state.MessageLimit;
        hasEarlier = state.Earlier; hasLater = state.Later; followingLatest = state.Latest; hasNewMessages = state.NewMessages; before = state.Before; messages = state.Messages; conversations = state.Conversations;
        searchMatches.Clear(); foreach (var pair in state.SearchMatches) searchMatches.Add(pair.Key, pair.Value);
        knowledgeMatches.Clear(); foreach (var pair in state.KnowledgeMatches) knowledgeMatches.Add(pair.Key, pair.Value);
        personChats.Clear(); foreach (var pair in state.PersonChats) personChats.Add(pair.Key, pair.Value);
        personChatsAccount = state.PersonAccount; personChatsDatabase = state.PersonDatabase;
        voiceModel = state.VoiceModel;
    }
}
