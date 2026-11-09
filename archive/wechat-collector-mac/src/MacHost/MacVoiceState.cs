using System.Globalization;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    sealed record VoiceItemState(string State, string Detail);
    string? voiceRegistryDatabase;
    static RecordIdentity VoiceIdentity(WechatDbMessage message) => new(message.AccountKey, message.ConversationUsername, message.ServerId.ToString(CultureInfo.InvariantCulture));
    void EnsureVoiceRegistryScope()
    {
        if (voiceRegistryDatabase == store.DatabasePath) return;
        if (voiceRegistryDatabase is not null) lock (voiceQueue) voiceQueue.Clear();
        voiceItems.Clear(); voiceFailures.Clear(); voiceRegistryDatabase = store.DatabasePath;
    }
    // Called under the controller gate. A late callback from a replaced store
    // cannot establish registrations in the new database.
    void ApplyVoiceUpdate(VoiceItemUpdate update, string database)
    {
        if (database != store.DatabasePath) return;
        EnsureVoiceRegistryScope();
        var id = VoiceIdentity(update.Message);
        if (string.IsNullOrEmpty(id.Account) || string.IsNullOrEmpty(id.Chat) || update.Message.Type != WechatDbMessageType.Voice) return;
        voiceItems[id] = new VoiceItemState(update.State, update.Detail);
        if (update.State == "failed" && (voiceFailures.Count < 500 || voiceFailures.ContainsKey(id))) voiceFailures[id] = update;
        else if (update.State == "completed") voiceFailures.TryRemove(id, out _);
        if (voiceItems.Count > 1000)
            foreach (var key in voiceItems.Where(pair => pair.Value.State is not ("queued" or "working")).Take(200).Select(pair => pair.Key)) voiceItems.TryRemove(key, out _);
    }
    void CancelPendingVoiceItems()
    {
        EnsureVoiceRegistryScope();
        foreach (var pair in voiceItems)
            if (pair.Value.State is "queued" or "working")
                voiceItems.TryUpdate(pair.Key, new VoiceItemState("cancelled", "已停止，已完成文字保留"), pair.Value);
    }
    int CurrentVoiceFailureCount { get { EnsureVoiceRegistryScope(); return voiceFailures.Keys.Count(id => id.Account == account); } }
    object[] VoiceFailuresState(IReadOnlyDictionary<string, string> names)
    {
        EnsureVoiceRegistryScope();
        return voiceFailures.Where(pair => pair.Key.Account == account).Select(pair => (object)new
        {
            id = LocalRecordReader.MessageId(pair.Key),
            title = names.GetValueOrDefault(pair.Key.Chat, pair.Key.Chat) + " · " + pair.Value.Message.CreateTime.ToLocalTime().ToString("MM-dd HH:mm:ss", CultureInfo.InvariantCulture),
            detail = pair.Value.Detail
        }).ToArray();
    }
    Dictionary<string, object> VoiceItemsState()
    {
        EnsureVoiceRegistryScope();
        var result = new Dictionary<string, object>(StringComparer.Ordinal);
        foreach (var message in messages.Where(message => message.AccountKey == account && message.ConversationUsername == chat && message.Type == WechatDbMessageType.Voice))
            if (voiceItems.TryGetValue(VoiceIdentity(message), out var item)) result[message.ServerId.ToString(CultureInfo.InvariantCulture)] = new { state = item.State, detail = item.Detail };
        return result;
    }
}
