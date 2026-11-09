using System.Globalization;
using System.Text.Json;
using WechatUiCollector.Collection;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacImportProvider : IWechatLocalMediaProvider
{
    readonly Lazy<MacWorkerPool> localMedia = new(() => new MacWorkerPool());
    public string ValidateMediaAccountRoot(string root,string account)
    {
        var resolved=ResolveAccountRoot(root);
        if (Path.GetFileName(resolved)!=account) throw new ArgumentException("消息与账号来源目录不匹配。");
        return resolved;
    }
    public string ProtectMediaOutput(string destination,string database)
        => MacOutputProtection.Resolve(destination,database,state,ArchiveDirectory,
            new[]{"bridge-token","bridge-entry.json","entry","bridge-errors.log","profile-ext-credentials.v1.json","db-keys.v1.json","messages.jsonl"}.Select(name=>Path.Combine(state,name)));
    public async Task<WechatImagePreviewResult> LoadMessageImageAsync(string root,WechatDbMessage message,CancellationToken token)
    {
        using var linked=CancellationTokenSource.CreateLinkedTokenSource(token,lifetime.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(90));
        root=ValidateMediaAccountRoot(root,message.AccountKey);
        try
        {
            var result=await MacMediaAccess.LoadAsync(localMedia.Value,ArchiveDirectory,root,message,"attachment",linked.Token);
            var bytes=await MacMediaAccess.ReadAsync(result.Path,linked.Token);
            var mime=MacMediaAccess.ImageMime(bytes);
            if(mime!=result.Mime)throw new IOException("图片回包类型不一致。");
            return new(true,bytes,MacMediaAccess.Extension(mime),mime,result.Path,root,null,false,true,false,false,WechatImageKeySource.None,null);
        }
        catch(MacAttachmentUnavailableException error){return WechatImagePreviewResult.Failed(error.Message);}
        catch(IOException){return WechatImagePreviewResult.Failed("没有可唯一验证的本地图片。");}
    }
    public async Task<byte[]> LoadMessageVoiceAsync(string root,WechatDbMessage message,CancellationToken token)
    {
        using var linked=CancellationTokenSource.CreateLinkedTokenSource(token,lifetime.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(90));
        root=ValidateMediaAccountRoot(root,message.AccountKey);
        var result=await MacMediaAccess.LoadAsync(localMedia.Value,ArchiveDirectory,root,message,"voice",linked.Token);
        var bytes=await MacMediaAccess.ReadAsync(result.Path,linked.Token);
        if(bytes.Length<44||!bytes.AsSpan(0,4).SequenceEqual("RIFF"u8)||!bytes.AsSpan(8,4).SequenceEqual("WAVE"u8))throw new IOException("语音不是已验证WAV。");
        return bytes;
    }
    public async Task<WechatImagePreviewResult> DecodeAccountImageAsync(string file,string? template,CancellationToken token)
    {
        using var linked=CancellationTokenSource.CreateLinkedTokenSource(token,lifetime.Token);
        linked.CancelAfter(TimeSpan.FromSeconds(90));
        file=Path.GetFullPath(file);
        string? accountRoot=null;
        for(var current=Path.GetDirectoryName(file);current is not null;current=Path.GetDirectoryName(current))
            if(Directory.Exists(Path.Combine(current,"db_storage"))){accountRoot=ResolveAccountRoot(current);break;}
        if(accountRoot is null)throw new ArgumentException("图片必须属于明确的微信账号目录。");
        MacMediaAccess.ValidateFile(file,[accountRoot]);
        string relative=Path.GetRelativePath(accountRoot,file).Replace(Path.DirectorySeparatorChar,'/');
        string? relativeTemplate=null;
        if(template is not null){template=Path.GetFullPath(template);MacMediaAccess.ValidateFile(template,[accountRoot]);relativeTemplate=Path.GetRelativePath(accountRoot,template).Replace(Path.DirectorySeparatorChar,'/');}
        var account=Path.GetFileName(accountRoot);
        var output=await localMedia.Value.ExchangeAsync(new{action="debugImageDecode",archive=ArchiveDirectory,sourceRoot=Path.GetDirectoryName(accountRoot),account,relativeFile=relative,relativeTemplate},linked.Token);
        using var json=JsonDocument.Parse(output);var data=json.RootElement;
        if(MacMediaAccess.Text(data,"status")!="ready"||!data.TryGetProperty("diagnosticIdentity",out var identity)||MacMediaAccess.Text(identity,"account")!=account||MacMediaAccess.Text(identity,"relativeFile")!=relative)
            throw new IOException("图片诊断未完成；来源或缓存密钥未通过验证。");
        var path=MacMediaAccess.ValidateFile(MacMediaAccess.Text(data,"path"),[Path.Combine(ArchiveDirectory,"media")]);
        var bytes=await MacMediaAccess.ReadAsync(path,linked.Token);var mime=MacMediaAccess.ImageMime(bytes);
        if(mime!=MacMediaAccess.Text(data,"mime"))throw new IOException("图片诊断格式不一致。");
        bool cached=data.TryGetProperty("keyCacheUsed",out var cache)&&cache.ValueKind==JsonValueKind.True;
        return new(true,bytes,MacMediaAccess.Extension(mime),mime,path,accountRoot,null,false,false,false,false,cached?WechatImageKeySource.ProtectedCache:WechatImageKeySource.None,null);
    }
}
