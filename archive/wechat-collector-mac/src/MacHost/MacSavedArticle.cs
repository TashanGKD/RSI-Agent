using System.Text.Json;
using WechatUiCollector.Models;
using WechatUiCollector.Safety;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    sealed record SavedArticleRead(Dictionary<string, object?>? Article, string? ArticleId, string Root, string? BodyPath);
    sealed record SavedArticleBinding(string Database, string Account, RecordIdentity Owner, string Link, SavedArticleRead Read);
    readonly Dictionary<string, SavedArticleBinding> savedArticleWindows = new(StringComparer.Ordinal);
    string SavedArticleRoot() => SourcePathProtection.WritablePath(official?.LastBodyOutputDirectory ?? official?.GetDefaultBodyOutputDirectory()
        ?? Path.Combine(Path.GetDirectoryName(store.DatabasePath)!, "article-bodies"));

    static string SavedArticleMarkdownPath(string root, string relative)
    {
        // The original harvester stores a relative MarkdownPath. Validate it
        // before ArticleByLinkAsync can open any file, using the existing source
        // protection for symlinks/hardlinks in addition to an exact root boundary.
        if (string.IsNullOrEmpty(relative) || Path.IsPathFullyQualified(relative) || relative.Split(Path.DirectorySeparatorChar).Any(part => part is "." or "..")
            || !Path.GetExtension(relative).Equals(".md", StringComparison.OrdinalIgnoreCase)) throw new IOException("已保存正文位置无法验证。");
        var path = SourcePathProtection.WritablePath(Path.Combine(root, relative));
        if (!path.StartsWith(Path.TrimEndingDirectorySeparator(root) + Path.DirectorySeparatorChar, StringComparison.Ordinal)) throw new IOException("已保存正文位置超出正文目录。");
        if (Directory.Exists(path)) throw new IOException("已保存正文位置不是文件。");
        return path;
    }
    async Task<SavedArticleRead> ReadSavedArticleAsync(string link, string root, CancellationToken token)
    {
        await using var reader = new LocalRecordReader(store.DatabasePath); await reader.OpenAsync(token);
        string? id = await reader.FindArticleIdentityAsync(link, token);
        string? verifiedPath = null;
        if (id is not null)
        {
            var identity = LocalRecordReader.ParseArticleId(id);
            var states = await store.ListOfficialAccountArticleBodyStatesAsync(identity.Biz, token);
            if (states.TryGetValue(identity.AppMsgId + "|" + identity.ItemIdx, out var body) && body.Status == OfficialAccountBodyStatus.Succeeded && body.MarkdownPath is not null)
                verifiedPath = SavedArticleMarkdownPath(root, body.MarkdownPath);
        }
        var article = await reader.ArticleByLinkAsync(link, root, 16000, token);
        if ((article?.GetValueOrDefault("articleId") as string) != id) throw new ArgumentException("文章身份已变化，请重新打开。");
        if (article?.GetValueOrDefault("bodyAvailable") is true)
        {
            if (verifiedPath is null || article.GetValueOrDefault("bodyPath") is not string actual || SourcePathProtection.WritablePath(actual) != verifiedPath)
                throw new IOException("已保存正文位置已变化。");
            // Recheck after the bounded original reader as well. No arbitrary
            // UI-provided file/URL is used at either point.
            verifiedPath = SavedArticleMarkdownPath(root, Path.GetRelativePath(root, verifiedPath));
        }
        return new SavedArticleRead(article, id, root, verifiedPath);
    }
    async Task ShowSavedArticleAsync(JsonElement command, CancellationToken token)
    {
        var owner = SelectedMessage(command); var link = WechatDbCard.Read(owner).Link;
        if (owner.AccountKey != account || !LocalRecordReader.IsOfficialArticleLink(link)) throw new ArgumentException("这条消息未包含可验证的公众号文章链接。");
        if (savedArticleWindows.Count >= 16) throw new ArgumentException("请先关闭一些已保存正文窗口，再打开新窗口。");
        string database = store.DatabasePath, selectedAccount = account;
        var read = await ReadSavedArticleAsync(link!.AbsoluteUri, SavedArticleRoot(), token);
        token.ThrowIfCancellationRequested();
        if (database != store.DatabasePath || selectedAccount != account) throw new ArgumentException("记录范围已变化，请重新打开文章。");
        string requestId = Guid.NewGuid().ToString("N");
        savedArticleWindows[requestId] = new SavedArticleBinding(database, account, new RecordIdentity(owner.AccountKey, owner.ConversationUsername, owner.ServerId.ToString(System.Globalization.CultureInfo.InvariantCulture)), link.AbsoluteUri, read);
        var article = read.Article; bool available = article?.GetValueOrDefault("bodyAvailable") is true;
        Post("chat", new { type = "macNative", command = "savedArticle", state = new
        {
            requestId, found = article is not null, title = article?.GetValueOrDefault("title") as string ?? "已保存的公众号正文",
            bodyAvailable = available, author = article?.GetValueOrDefault("author")?.ToString(), publishedAt = article?.GetValueOrDefault("publishedAt")?.ToString(),
            content = available ? article?.GetValueOrDefault("content") as string : null, contentTruncated = article?.GetValueOrDefault("contentTruncated") is true,
            canOpenFile = available && read.BodyPath is not null, bodyPath = available ? read.BodyPath : null
        } });
    }
    async Task SavedArticleActionAsync(JsonElement command, CancellationToken token)
    {
        if (command.EnumerateObject().Any(property => property.Name is not ("action" or "requestId" or "operation"))) throw new ArgumentException("正文窗口操作不能指定路径或链接。");
        string requestId = Text(command, "requestId"), operation = Text(command, "operation");
        if (!savedArticleWindows.TryGetValue(requestId, out var binding)) throw new ArgumentException("正文窗口已关闭或过期，请重新打开。");
        if (operation == "close")
        {
            savedArticleWindows.Remove(requestId); Post("chat", new { type = "macNative", command = "closeSavedArticle", requestId }); return;
        }
        if (operation is not ("open" or "collect")) throw new ArgumentException("未知正文窗口操作。");
        if (binding.Database != store.DatabasePath || binding.Account != account || binding.Read.Root != SavedArticleRoot()) throw new ArgumentException("正文窗口的账号或保存位置已变化，请重新打开。");
        await using (var reader = new LocalRecordReader(store.DatabasePath))
        {
            await reader.OpenAsync(token); WechatDbMessage owner;
            try { owner = await reader.MessageAsync(binding.Owner, token); }
            catch (KeyNotFoundException) { throw new ArgumentException("原文章消息已不可用，请重新打开。"); }
            var link = WechatDbCard.Read(owner).Link;
            if (!LocalRecordReader.IsOfficialArticleLink(link) || link!.AbsoluteUri != binding.Link) throw new ArgumentException("原文章链接已变化，请重新打开。");
        }
        var current = await ReadSavedArticleAsync(binding.Link, binding.Read.Root, token);
        if (current.ArticleId != binding.Read.ArticleId || current.BodyPath != binding.Read.BodyPath) throw new ArgumentException("已保存文章或正文位置已变化，请重新打开。");
        if (operation == "open")
        {
            if (binding.Read.Article?.GetValueOrDefault("bodyAvailable") is not true || current.Article?.GetValueOrDefault("bodyAvailable") is not true || current.BodyPath is null)
                throw new ArgumentException("这篇文章没有可打开的本地正文。");
            Post("chat", new { type = "macNative", command = "savedArticleOpen", requestId, path = current.BodyPath }); return;
        }
        if (binding.Read.Article?.GetValueOrDefault("bodyAvailable") is true) throw new ArgumentException("正文已经保存，请打开本地正文文件。");
        // The original PrepareArticle only fills the original URL. It does not
        // parse, fetch, invoke a worker or change the existing collection throttle.
        if (officialWeb is null) await OfficialAsync(JsonSerializer.SerializeToElement(new { action = "ready" }), token);
        officialWeb!.PrepareArticle(binding.Link);
        selectedTab = "OfficialAccountTab";
        Post("navigation", new { type = "macNavigation", id = selectedTab });
        Post("navigation", new { type = "navigation", selected = selectedTab, items = Tabs });
        savedArticleWindows.Remove(requestId); Post("chat", new { type = "macNative", command = "closeSavedArticle", requestId });
    }
}
