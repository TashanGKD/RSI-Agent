using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

// The original LocalChatsView.MessageRow rules, with WPF presentation types removed.
public static class MacMessagePresentation
{
    public static object Row(WechatDbMessage message, WechatDbMessage? previous, IReadOnlyDictionary<string, string> names, int index, bool group, string? avatarUrl = null)
    {
        var card = WechatDbCard.Read(message);
        var systemText = WechatSystemMessage.Read(message);
        bool system = systemText is not null, self = message.IsSelf;
        bool media = message.Type is WechatDbMessageType.Voice or WechatDbMessageType.Video;
        bool image = card.ImageHash is not null || message.Type == WechatDbMessageType.Image;
        bool location = card.Location is not null;
        var time = message.CreateTime.ToLocalTime();
        var body = systemText ?? (message.PlainContent is not null ? message.Type is WechatDbMessageType.Text or WechatDbMessageType.System ? message.PlainContent : WechatDbMessagePresentation.Placeholder(message) + " " + message.PlainContent : WechatDbMessagePresentation.ReadableFallback(message) ?? WechatDbMessagePresentation.Placeholder(message));
        if (!string.IsNullOrEmpty(card.Title) && (card.Link is not null || card.FileName is not null || card.KindLabel is not null)) body = card.Title;
        if (card.KindLabel == "通话记录") body = card.CallSummary ?? (message.RawContent is null ? "已保存记录缺少通话正文，可从“更多 → 全面重新解析”尝试补回" : "通话原文已保存，当前解析器尚未识别其状态");
        var heading = system ? "" : !message.HasKnownDirection || group && !self && WechatDbMessagePresentation.StartsReadingGroup(message, previous) ? message.SenderDisplayName ?? (message.SenderUsername is null ? "发送者未知" : names.GetValueOrDefault(message.SenderUsername, message.SenderUsername)) : "";
        var status = message.ParseStatus == WechatDbMessageParseStatus.Failed ? "解析失败" : "";
        if (message.RawContent is null && message.Type is WechatDbMessageType.Image or WechatDbMessageType.Emoji or WechatDbMessageType.Location or WechatDbMessageType.AppMsg) status = "已保存记录缺少消息描述，可从“更多 → 全面重新解析”尝试补回";
        if (!message.HasKnownDirection) status = "发送方向未知";
        if (system) status = "";
        var detail = card.Link?.Host ?? (card.DurationSeconds is int duration ? $"{duration} 秒" : card.FileDetail);
        return new
        {
            index, id = message.ServerId.ToString(), self, system, cardKind = card.KindLabel, linkUrl = card.Link?.AbsoluteUri, sourceName = card.SourceName, duration = card.DurationSeconds,
            avatar = avatarUrl, senderId = message.SenderUsername ?? message.SelfUsername, heading,
            time = previous is null || previous.CreateTime.ToLocalTime().Date != time.Date ? time.ToString("yyyy年M月d日 HH:mm") : message.CreateTime - previous.CreateTime >= TimeSpan.FromMinutes(5) ? time.ToString("HH:mm") : "",
            exactTime = time.ToString("yyyy-MM-dd HH:mm:ss"), body = media || image || location || message.Type == WechatDbMessageType.Emoji ? "" : body,
            voice = message.Type == WechatDbMessageType.Voice, transcript = message.Transcript, transcriptVersion = message.TranscriptVersion,
            label = location || card.Quote is not null ? "" : card.KindLabel ?? "", description = card.Description ?? "", detail = !media && card.KindLabel != "通话记录" ? detail : "", status, image, video = message.Type == WechatDbMessageType.Video,
            media = media ? (message.Type == WechatDbMessageType.Voice ? "▶  语音" : "▶  视频") + (card.DurationSeconds is int length ? $" · {length} 秒" : "") : null,
            sticker = message.Type == WechatDbMessageType.Emoji ? card.EmojiUrl is null || card.EmojiHash is null ? "本地未保存可预览表情" : "加载表情（联网）" : null,
            forwarded = card.Forwarded is null ? null : $"查看聊天记录 · {card.Forwarded.Items.Count} 条 →", quote = card.Quote is null ? null : (card.Quote.SenderName ?? "原消息") + "：" + card.Quote.Summary,
            location = location ? (card.Location!.Name ?? "位置") + "\n" + string.Join("\n", new[] { card.Location.Address, card.Location.Coordinates }.Where(s => !string.IsNullOrEmpty(s))) : null,
            link = card.Link is not null, file = card.FileName is not null, article = LocalRecordReader.IsOfficialArticleLink(card.Link)
        };
    }
}
