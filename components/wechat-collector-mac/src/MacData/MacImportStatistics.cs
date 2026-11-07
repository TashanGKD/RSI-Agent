using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

internal sealed class MacImportStatistics
{
    internal readonly HashSet<string> Conversations = new(StringComparer.Ordinal);
    internal int Messages, Parsed, Failed, Partial, Inserted, Updated;
    internal void Read(IReadOnlyList<WechatDbMessage> messages)
    {
        Messages += messages.Count;
        foreach (var message in messages)
        {
            Conversations.Add(message.ConversationUsername);
            switch (message.ParseStatus) { case WechatDbMessageParseStatus.Parsed: Parsed++; break; case WechatDbMessageParseStatus.Partial: Partial++; break; default: Failed++; break; }
        }
    }
    internal WechatDbMessageImportResult Result(bool success, long elapsed = 0)
        => new(success, Conversations.Count, Messages, Parsed, Failed, true, elapsed, success ? null : "本地消息来源未完成导入；已提交批次和备份保留。")
        { InsertedCount = Inserted, UpdatedCount = Updated, PartialCount = Partial, FailedDatabaseCount = success ? 0 : 1 };
}
