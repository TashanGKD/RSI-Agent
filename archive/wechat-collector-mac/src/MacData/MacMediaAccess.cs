using System.Globalization;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;
using System.Text.Json;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed record MacMediaFile(string Path, string Mime);

// Only this type's fixed messages may cross the Host feedback boundary.
public sealed class MacAttachmentUnavailableException : IOException
{
    internal MacAttachmentUnavailableException(bool identified) : base(identified
        ? "当前账号的所选本地来源中未找到对应附件。可尝试在微信中打开或下载后重试。"
        : "这条消息未取得可核对的本地附件关联信息。请在微信中查看该消息。") { }
}

// A thin IPC binding/validation layer; pooling and actual decoders stay unchanged.
public static class MacMediaAccess
{
    public static async Task<MacMediaFile> LoadAsync(MacWorkerPool pool, string archive, string accountRoot, WechatDbMessage message, string action, CancellationToken token)
    {
        if (action is not ("attachment" or "voice")) throw new ArgumentException("未知媒体操作。");
        var source = message.SourceSummary is { } summary && Regex.IsMatch(summary, @"\Amessage/(biz_)?message_[0-9]+\.db\z") ? summary : null;
        if (string.IsNullOrEmpty(message.AccountKey) || string.IsNullOrEmpty(message.ConversationUsername) || message.ServerId == 0 || message.LocalId < 0)
            throw new ArgumentException("消息身份或来源不完整。");
        var request = new Dictionary<string,object> { ["archive"]=archive, ["action"]=action, ["sourceRoot"]=System.IO.Path.GetDirectoryName(accountRoot)!, ["account"]=message.AccountKey,
            ["chat"]=message.ConversationUsername, ["serverId"]=message.ServerId.ToString(CultureInfo.InvariantCulture), ["localId"]=message.LocalId, ["createTime"]=message.CreateTime.ToUnixTimeSeconds() };
        if(source is not null) request["source"]=source;
        var output = await pool.ExchangeAsync(request, token);
        using var json = JsonDocument.Parse(output); var data = json.RootElement;
        if (Text(data, "status") != "ready")
        {
            if (action == "attachment" && Text(data, "status") == "missing")
            {
                // Never surface the worker's arbitrary error text, paths or unknown codes.
                if (Text(data, "errorCode") == "attachment_not_local") throw new MacAttachmentUnavailableException(true);
                if (Text(data, "errorCode") == "attachment_identity_unavailable") throw new MacAttachmentUnavailableException(false);
            }
            throw new IOException("没有可唯一验证的本地媒体。");
        }
        if (!data.TryGetProperty("messageIdentity", out var identity) || Text(identity,"account") != message.AccountKey ||
            Text(identity,"chat") != message.ConversationUsername || Text(identity,"serverId") != message.ServerId.ToString(CultureInfo.InvariantCulture) ||
            (source is not null && Text(identity,"source") != source) || !Long(identity,"localId",message.LocalId) || !Long(identity,"createTime",message.CreateTime.ToUnixTimeSeconds()))
            throw new IOException("媒体回包与所选消息不一致。");
        var mime = Text(data,"mime");
        if ((action == "voice" && mime != "audio/wav") || (action == "attachment" && message.Type is (WechatDbMessageType.Image or WechatDbMessageType.Emoji) && !mime.StartsWith("image/",StringComparison.Ordinal)))
            throw new IOException("媒体类型与消息不一致。");
        var path = ValidateFile(Text(data,"path"), [System.IO.Path.Combine(archive,"media"), accountRoot]);
        return new(path,mime);
    }
    public static string ValidateFile(string path, IReadOnlyList<string> roots)
    {
        if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException("Mac media validation requires macOS.");
        var accepted = MacForwardResources.ValidatePath(path, roots);
        int result = RuntimeInformation.ProcessArchitecture == Architecture.X64 ? LStatInode64(accepted, out var info) : LStat(accepted,out info);
        if (result != 0 || (info.Mode & 0xf000) != 0x8000 || info.Size <= 0 || info.Size > 128L*1024*1024)
            throw new IOException("本地媒体不是有效普通文件。");
        return accepted;
    }
    internal static async Task<byte[]> ReadAsync(string path, CancellationToken token)
    {
        using var input=File.OpenRead(path); using var output=new MemoryStream(); var buffer=new byte[65536]; int count;
        while((count=await input.ReadAsync(buffer,token))>0){if(output.Length+count>128L*1024*1024)throw new IOException("本地媒体过大。");await output.WriteAsync(buffer.AsMemory(0,count),token);}
        if(output.Length==0)throw new IOException("本地媒体为空。");
        return output.ToArray();
    }
    internal static string ImageMime(ReadOnlySpan<byte> data)
    {
        if (data.StartsWith(new byte[]{137,80,78,71,13,10,26,10})) return "image/png";
        if (data.StartsWith(new byte[]{255,216,255})) return "image/jpeg";
        if (data.StartsWith("GIF87a"u8)||data.StartsWith("GIF89a"u8)) return "image/gif";
        if (data.Length>=12&&data[..4].SequenceEqual("RIFF"u8)&&data.Slice(8,4).SequenceEqual("WEBP"u8)) return "image/webp";
        throw new IOException("本地图片格式未通过校验。");
    }
    internal static string Extension(string mime)=>mime switch {"image/png"=>".png","image/jpeg"=>".jpg","image/gif"=>".gif","image/webp"=>".webp",_=>throw new IOException("未知图片格式。")};
    internal static string Text(JsonElement value,string name)=>value.TryGetProperty(name,out var item)&&item.ValueKind==JsonValueKind.String?item.GetString()!:"";
    static bool Long(JsonElement value,string name,long expected)=>value.TryGetProperty(name,out var item)&&item.TryGetInt64(out var number)&&number==expected;
    [StructLayout(LayoutKind.Explicit,Size=256)]struct DarwinStat{[FieldOffset(4)]public ushort Mode;[FieldOffset(96)]public long Size;}
    [DllImport("libSystem.B.dylib",EntryPoint="lstat",SetLastError=true)]static extern int LStat([MarshalAs(UnmanagedType.LPUTF8Str)]string path,out DarwinStat value);
    [DllImport("libSystem.B.dylib",EntryPoint="lstat$INODE64",SetLastError=true)]static extern int LStatInode64([MarshalAs(UnmanagedType.LPUTF8Str)]string path,out DarwinStat value);
}
