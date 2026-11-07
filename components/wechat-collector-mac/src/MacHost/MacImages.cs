using System.Text.Json;
using WechatUiCollector.Safety;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    WechatDbMessage[] imageMessages = [];
    int imageIndex, imageVersion;
    string imageStatus = "", imagePath = "", imageUrl = "", imageMime = "", imageSavedPath = "";
    bool imageBusy;
    string imageKind = "image";
    Func<CancellationToken, Task<(string Path, string Mime, string Url)>>? trustedSingleImageLoader;
    void OpenTrustedSingleImage(WechatDbMessage parent, string path, string mime, Func<CancellationToken, Task<(string Path, string Mime, string Url)>> reload) => OpenTrustedImageCore(parent, path, mime, reload, "image");
    void OpenTrustedImageCore(WechatDbMessage parent, string path, string mime, Func<CancellationToken, Task<(string Path, string Mime, string Url)>> reload, string kind, byte[]? trustedBytes = null)
    {
        imageKind = kind;
        trustedSingleImageLoader = reload; imageMessages = [parent]; imageIndex = 0;
        imageVersion++; imageBusy = false; imagePath = path; imageMime = mime; imageSavedPath = ""; imageStatus = "已保存图片";
        if (kind == "sticker") imageUrl = StickerResource(path, mime, trustedBytes ?? throw new ArgumentException("表情资源缺少已验证字节。"));
        else { var id = Guid.NewGuid().ToString("N"); mediaResources[id] = (path, mime); imageUrl = "/preview/" + id; }
        if (mediaResources.Count > 256) mediaResources.TryRemove(mediaResources.Keys.First(), out _);
        PublishImage(); Post("chat", new { type = "macNative", command = "imagePage", url = "/Common/image.html", kind = imageKind });
    }
    async Task OpenImagesAsync(WechatDbMessage selected, CancellationToken token)
    {
        imageKind = "image";
        trustedSingleImageLoader = null;
        imageMessages = selected.Type == WechatDbMessageType.Emoji ? [selected] : messages.Where(m => m.Type == WechatDbMessageType.Image || WechatDbCard.Read(m).ImageHash is not null).ToArray();
        imageIndex = Array.FindIndex(imageMessages, m => m.ServerId == selected.ServerId);
        if (imageIndex < 0) { imageMessages = [selected]; imageIndex = 0; }
        await LoadImageAsync(token);
        Post("chat", new { type = "macNative", command = "imagePage", url = "/Common/image.html" });
    }
    async Task LoadImageAsync(CancellationToken token)
    {
        imageBusy = true; imageVersion++; imagePath = imageUrl = imageSavedPath = ""; imageStatus = "正在加载图片…"; PublishImage();
        try { var result = trustedSingleImageLoader is { } reload ? await reload(token) : await LoadMediaAsync(imageMessages[imageIndex], token, foreground: true); imagePath = result.Path; imageUrl = result.Url; imageMime = result.Mime; imageStatus = "已保存图片"; }
        catch (Exception error) when (error is not OutOfMemoryException) { imageStatus = error is ArgumentException or MacAttachmentUnavailableException ? error.Message : error is OperationCanceledException ? "图片读取已取消。" : "本地图片读取未完成，可以重试。"; }
        finally { imageBusy = false; PublishImage(); }
    }
    void PublishImage() => Post("image", new { type = "image", version = imageVersion, index = imageIndex, count = imageMessages.Length, busy = imageBusy, status = imageStatus, canPrevious = imageIndex > 0, canNext = imageIndex + 1 < imageMessages.Length, paged = false, loaded = imagePath.Length > 0, canReveal = imagePath.Length > 0, src = imageUrl.Length > 0 ? imageUrl : null });
    async Task ImageAsync(JsonElement command, CancellationToken token)
    {
        string action = Text(command, "action");
        if (action == "ready") { PublishImage(); return; }
        if (action is "previous" or "next")
        {
            int target = imageIndex + (action == "next" ? 1 : -1);
            if (target >= 0 && target < imageMessages.Length) { imageIndex = target; await LoadImageAsync(token); }
            return;
        }
        if (action == "retry") { await LoadImageAsync(token); return; }
        if (action == "close") { if (stickerCancellation is { } pending) TryCancel(pending); Post("image", new { type = "macNative", command = "closeImage" }); return; }
        if (imageBusy || imagePath.Length == 0 || Text(command, "version") != imageVersion.ToString()) return;
        if (imageKind == "sticker" && trustedSingleImageLoader is { } verify)
        {
            var verified = await verify(token); imagePath = verified.Path; imageMime = verified.Mime;
        }
        switch (action)
        {
            case "copy": Post("image", new { type = "macNative", command = "copyImage", path = imagePath }); imageStatus = "图片已复制，可粘贴到其他应用"; break;
            case "copyFile":
                var clipboard = Path.Combine(directory, "media/clipboard"); ProtectedFileSystem.CreateDirectory(clipboard);
                imageSavedPath = Path.Combine(clipboard, Guid.NewGuid().ToString("N") + ImageExtension());
                ProtectedFileSystem.Copy(imagePath, imageSavedPath);
                Post("image", new { type = "macNative", command = "copyFile", path = imageSavedPath }); imageStatus = "文件已复制，可粘贴到支持文件的应用"; break;
            case "save": Post("image", new { type = "macNative", command = "saveImage", page = "image", filename = "微信图片" + ImageExtension(), version = imageVersion }); break;
            case "saveImage":
                var path = Text(command, "path"); if (path.Length > 0) { ProtectedFileSystem.Copy(imagePath, SafeUserOutput(path), overwrite: true); imageSavedPath = path; imageStatus = "图片已保存"; } break;
            case "folder": Post("image", new { type = "macNative", command = "reveal", path = imageSavedPath.Length > 0 ? imageSavedPath : imagePath }); imageStatus = "已定位保存的图片"; break;
            default: throw new ArgumentException("未知图片操作。");
        }
        PublishImage();
    }
    string ImageExtension() => imageMime switch { "image/jpeg" => ".jpg", "image/gif" => ".gif", "image/webp" => ".webp", _ => ".png" };
}
