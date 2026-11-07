using System.Globalization;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    readonly Dictionary<string, string> personChats = new(StringComparer.Ordinal);
    string? personChatsAccount, personChatsDatabase;
    void InvalidatePersonChats() { personChats.Clear(); personChatsAccount = personChatsDatabase = null; }
    void RegisterPersonChats(Dictionary<string, object?> person)
    {
        InvalidatePersonChats();
        if (person.GetValueOrDefault("chats") is not IEnumerable<Dictionary<string, object>> rows) throw new InvalidDataException("人物会话列表不可用。");
        foreach (var row in rows)
        {
            if (personChats.Count >= 200 || row.GetValueOrDefault("chatId") is not string id || string.IsNullOrEmpty(id)
                || row.GetValueOrDefault("displayName") is not string name || !personChats.TryAdd(id, name))
            { InvalidatePersonChats(); throw new InvalidDataException("人物会话列表无效。"); }
        }
        personChatsAccount = account; personChatsDatabase = store.DatabasePath;
    }
    async Task OpenPersonChatAsync(string target, CancellationToken token)
    {
        if (personChatsAccount != account || personChatsDatabase != store.DatabasePath)
        { InvalidatePersonChats(); throw new ArgumentException("人物会话列表已过期，请重新打开人物资料。"); }
        if (!personChats.ContainsKey(target)) throw new ArgumentException("该会话不在当前人物已返回的会话列表中。");
        var rows = (await store.QueryDbMessagesAsync(account, target, 100, null, null, null, token)).Reverse().ToArray();
        SetRecordNavigation(target, rows, null, null);
    }
    async Task OpenVoiceFailureAsync(string id, CancellationToken token)
    {
        EnsureVoiceRegistryScope();
        var identity = LocalRecordReader.ParseIdentity(id);
        if (identity.Account != account || !voiceFailures.TryGetValue(identity, out var failed)) throw new ArgumentException("该语音失败项已过期或不属于当前账号。");
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        WechatDbMessage current;
        try { current = await reader.MessageAsync(identity, token); }
        catch (KeyNotFoundException) { throw new ArgumentException("这条语音消息已不可用，请重新读取。"); }
        if (current.Type != WechatDbMessageType.Voice || VoiceIdentity(current) != VoiceIdentity(failed.Message)) throw new ArgumentException("这条语音消息已不可用，请重新读取。");
        var position = await store.FindDbMessagePositionAsync(account, identity.Chat, long.Parse(identity.ServerId, CultureInfo.InvariantCulture), token);
        if (!position.Found) throw new ArgumentException("这条语音消息已不可用，请重新读取。");
        var rows = (await store.QueryDbMessagesAsync(account, identity.Chat, 100, null, null, position.Before, token)).Reverse().ToArray();
        if (!rows.Any(row => VoiceIdentity(row) == identity)) throw new ArgumentException("这条语音消息已更新，请重新读取。");
        SetRecordNavigation(identity.Chat, rows, position.Before, identity.ServerId);
        feedback = "已定位语音失败项，可向两端阅读上下文。";
    }
    void SetRecordNavigation(string target, IReadOnlyList<WechatDbMessage> rows, WechatDbPageCursor? cursor, string? scroll)
    {
        ResetReadingPosition(); chat = target; selection++; from = to = null; before = cursor; messageLimit = 100;
        messages = rows; version++; hasEarlier = rows.Count == 100; hasLater = cursor is not null; followingLatest = cursor is null; scrollTarget = scroll;
    }
}
