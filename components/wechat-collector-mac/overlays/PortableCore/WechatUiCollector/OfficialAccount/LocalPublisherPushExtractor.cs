using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Xml;
using System.Xml.Linq;
using WechatUiCollector.Models;
using WechatUiCollector.Storage;
using WechatUiCollector.WechatDb;

namespace WechatUiCollector.OfficialAccount;

internal enum PublisherPushOutcome { Complete, Partial, Unsupported, Invalid, LimitReached, Cancelled }
internal sealed record PublisherPushOrigin(RecordIdentity Message, string? SenderUsername, DateTimeOffset ReceivedAt);
// Contains signed source locators for internal resolution. Never log or expose
// this result as diagnostics. All publisher metadata is locally declared.
internal sealed record PublisherPushCandidate(OfficialAccountArticle Article, PublisherPushOrigin Origin, string? DeclaredPublisherName)
{
    internal bool ServerVerified => false;
    internal IReadOnlyList<string> AlternateContentUrls { get; init; } = Array.Empty<string>();
    internal int AlternateContentUrlCount => AlternateContentUrls.Count;
}
internal sealed record PublisherPushResult(PublisherPushOutcome Outcome, string Coverage,
    IReadOnlyList<PublisherPushCandidate> Candidates, int ItemsExamined, int RejectedItems,
    int Duplicates, int OutputMetadataBytes, string? Detail);

internal static class LocalPublisherPushExtractor
{
    const int MaximumTextBytes = 256 * 1024, MaximumDepth = 32, MaximumNodes = 4096,
        MaximumItems = 64, MaximumUrlBytes = 8192, MaximumOutputBytes = 256 * 1024;
    static readonly UTF8Encoding Utf8 = new(false, true);

    internal static PublisherPushResult Extract(WechatDbMessage message, string? expectedBiz = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(message);
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (message.Type != WechatDbMessageType.AppMsg || message.AppMsgSubType != 5)
                return Empty(PublisherPushOutcome.Unsupported, "message-type");
            string? raw = message.RawContent;
            if (string.IsNullOrEmpty(raw)) return Empty(PublisherPushOutcome.Unsupported, "raw-content-missing");
            // Length rejects before encoding or XML allocation. Strict GetByteCount
            // validates UTF16 without allocating another payload buffer.
            if (raw.Length > MaximumTextBytes || Utf8.GetByteCount(raw) > MaximumTextBytes)
                return Empty(PublisherPushOutcome.LimitReached, "input-limit");
            if (string.IsNullOrWhiteSpace(raw)) return Empty(PublisherPushOutcome.Unsupported, "raw-content-missing");
            if (expectedBiz is not null && !ValidBiz(expectedBiz)) return Empty(PublisherPushOutcome.Invalid, "expected-biz-invalid");
            string xml = raw;
            if (message.ConversationUsername.EndsWith("@chatroom", StringComparison.Ordinal) && !string.IsNullOrEmpty(message.SenderUsername))
                xml = WechatDbContentDecoder.StripSenderPrefix(xml, message.SenderUsername);
            PublisherPushResult? preflight = Preflight(xml, cancellationToken);
            if (preflight is not null) return preflight;
            using var reader = XmlReader.Create(new StringReader(xml), Settings());
            XElement? root = XDocument.Load(reader).Root;
            XElement? app;
            if (root?.Name == "appmsg") app = root;
            else if (root?.Name == "msg")
            {
                var apps = root.Elements("appmsg").ToArray();
                if (apps.Length > 1) return Empty(PublisherPushOutcome.Invalid, "ambiguous-appmsg");
                app = apps.SingleOrDefault();
            }
            else return Empty(PublisherPushOutcome.Unsupported, "xml-schema");
            if (app is null) return Empty(PublisherPushOutcome.Unsupported, "appmsg-missing");
            if (!Scalar(app, "type", out string? type) || (type is not null && type != "5"))
                return Empty(PublisherPushOutcome.Unsupported, "appmsg-type");
            var readers = app.Elements("mmreader").ToArray();
            if (readers.Length > 1) return Empty(PublisherPushOutcome.Invalid, "ambiguous-mmreader");
            bool push = readers.Length == 1;
            string coverage = push ? "local-publisher-push" : "local-shared-card";
            Scalar(app, "sourcedisplayname", out string? declaredName);
            declaredName ??= app.Element("appinfo")?.Element("appname")?.Value.Trim();
            var origin = new PublisherPushOrigin(new RecordIdentity(message.AccountKey, message.ConversationUsername,
                message.ServerId.ToString(CultureInfo.InvariantCulture)), message.SenderUsername, message.CreateTime);
            var candidates = new List<PublisherPushCandidate>();
            var identities = new Dictionary<string, int>(StringComparer.Ordinal);
            int examined = 0, rejected = 0, duplicates = 0, outputBytes = 0;
            bool partial = false, limited = false;
            string? detail = null;
            if (string.IsNullOrEmpty(message.AccountKey) || string.IsNullOrEmpty(message.ConversationUsername) || message.ServerId <= 0)
                Partial("origin-incomplete");
            if (push)
            {
                foreach (XElement item in readers[0].Elements("category").SelectMany(category => category.Elements("item")))
                {
                    cancellationToken.ThrowIfCancellationRequested(); examined++;
                    Add(item, isItem: true);
                    if (limited) break;
                }
                if (examined == 0) Partial("push-items-missing");
            }
            if (!limited)
            {
                // Optional direct head is inspected only at its documented path.
                // Items run first so duplicate heads cannot erase item metadata.
                if (app.Element("url") is not null) Add(app, isItem: false);
                else if (!push) { rejected++; Partial("header-url-missing"); }
            }
            cancellationToken.ThrowIfCancellationRequested();
            return new PublisherPushResult(limited ? PublisherPushOutcome.LimitReached : partial ? PublisherPushOutcome.Partial : PublisherPushOutcome.Complete,
                coverage, candidates.AsReadOnly(), examined, rejected, duplicates, outputBytes, detail);

            void Partial(string code) { partial = true; detail ??= code; }
            void Limit(string code) { limited = true; detail = code; }
            void Add(XElement element, bool isItem)
            {
                if (!Scalar(element, "url", out string? url) || !Scalar(element, "title", out string? title) || !Scalar(element, "pub_time", out string? time))
                { rejected++; Partial("ambiguous-fields"); return; }
                if (url is not null && (url.Length > MaximumUrlBytes || Utf8.GetByteCount(url) > MaximumUrlBytes))
                { rejected++; Limit("url-limit"); return; }
                if (!TryArticle(url, expectedBiz, out string? biz, out string? mid, out int idx, out string? sn, out Uri? canonical, out string reason))
                { rejected++; Partial(reason); return; }
                DateTimeOffset? published = null;
                if (isItem)
                {
                    if (long.TryParse(time, NumberStyles.None, CultureInfo.InvariantCulture, out long seconds) && seconds > 0)
                    {
                        try { published = DateTimeOffset.FromUnixTimeSeconds(seconds); }
                        catch (ArgumentOutOfRangeException) { Partial("item-time-invalid"); }
                    }
                    else Partial("item-time-missing-or-invalid");
                }
                if (string.IsNullOrWhiteSpace(title)) { title = null; Partial("title-missing"); }
                var article = new OfficialAccountArticle(biz!, mid!, idx, sn, title, null, url, canonical, published, null, null,
                    ParseStatus.Parsed, push ? "LocalPublisherPush" : "LocalSharedArticle", "Local declared metadata; server identity unverified.");
                if (identities.TryGetValue(article.ArticleKey, out int prior))
                {
                    duplicates++;
                    PublisherPushCandidate primary = candidates[prior];
                    // Every URL already passed its own identity/canonical checks.
                    // Same-key signed locator refresh is not a coverage gap.
                    if (string.Equals(primary.Article.ContentUrl, url, StringComparison.Ordinal)
                        || primary.AlternateContentUrls.Contains(url!, StringComparer.Ordinal)) return;
                    long alternateCharge = 64L + Utf8.GetByteCount(url!);
                    if (alternateCharge > MaximumOutputBytes - outputBytes) { Limit("output-metadata-limit"); return; }
                    var alternates = primary.AlternateContentUrls.ToList();
                    alternates.Add(url!);
                    candidates[prior] = primary with { AlternateContentUrls = alternates.AsReadOnly() };
                    outputBytes += (int)alternateCharge;
                    return;
                }
                if (candidates.Count >= MaximumItems) { Limit("candidate-count-limit"); return; }
                var candidate = new PublisherPushCandidate(article, origin, declaredName);
                long charge = MetadataCharge(candidate);
                if (charge > MaximumOutputBytes - outputBytes) { Limit("output-metadata-limit"); return; }
                identities.Add(article.ArticleKey, candidates.Count);
                candidates.Add(candidate); outputBytes += (int)charge;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { return Empty(PublisherPushOutcome.Cancelled, "cancelled"); }
        catch (EncoderFallbackException) { return Empty(PublisherPushOutcome.Invalid, "invalid-unicode"); }
        catch (XmlException) { return Empty(PublisherPushOutcome.Invalid, "invalid-xml"); }
    }

    static XmlReaderSettings Settings() => new() {
        DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = MaximumTextBytes,
        IgnoreComments = false, IgnoreWhitespace = false
    };
    static PublisherPushResult? Preflight(string xml, CancellationToken token)
    {
        using var reader = XmlReader.Create(new StringReader(xml), Settings());
        var path = new List<string>(); int nodes = 0, items = 0;
        while (reader.Read())
        {
            token.ThrowIfCancellationRequested();
            nodes += 1 + reader.AttributeCount;
            if (nodes > MaximumNodes) return Empty(PublisherPushOutcome.LimitReached, "xml-node-limit");
            if (reader.NodeType != XmlNodeType.Element) continue;
            if (reader.Depth + 1 > MaximumDepth) return Empty(PublisherPushOutcome.LimitReached, "xml-depth-limit");
            if (reader.NamespaceURI.Length != 0) return Empty(PublisherPushOutcome.Unsupported, "xml-namespace");
            while (path.Count > reader.Depth) path.RemoveAt(path.Count - 1);
            path.Add(reader.LocalName);
            bool directItem = path.SequenceEqual(new[] { "msg", "appmsg", "mmreader", "category", "item" })
                || path.SequenceEqual(new[] { "appmsg", "mmreader", "category", "item" });
            if (directItem && ++items > MaximumItems) return Empty(PublisherPushOutcome.LimitReached, "item-count-limit");
        }
        return null;
    }
    static bool Scalar(XElement element, string name, out string? value)
    {
        XElement[] fields = element.Elements(name).ToArray();
        if (fields.Any(field => field.HasElements)) { value = null; return false; }
        string[] values = fields.Select(field => field.Value.Trim()).Distinct(StringComparer.Ordinal).ToArray();
        value = values.Length == 1 && values[0].Length > 0 ? values[0] : null;
        return values.Length <= 1;
    }
    static bool ValidBiz(string value) => value.Length is > 0 and <= 1024 && !string.IsNullOrWhiteSpace(value)
        && !value.Any(character => char.IsControl(character) || character == '|');
    static bool TryArticle(string? url, string? expectedBiz, out string? biz, out string? mid, out int idx,
        out string? sn, out Uri? canonical, out string reason)
    {
        biz = mid = sn = null; idx = 0; canonical = null; reason = "locator-invalid";
        if (string.IsNullOrWhiteSpace(url)) { reason = "locator-missing"; return false; }
        if (url.Any(char.IsControl) || !ValidEscapes(url) || !Uri.TryCreate(url, UriKind.Absolute, out Uri? uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            || !string.Equals(uri.Host, "mp.weixin.qq.com", StringComparison.OrdinalIgnoreCase)
            || uri.UserInfo.Length != 0 || !uri.IsDefaultPort) return false;
        if (uri.AbsolutePath != "/s") { reason = uri.AbsolutePath.StartsWith("/s/", StringComparison.Ordinal) ? "short-locator-pending" : "locator-path-unsupported"; return false; }
        var query = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string part in uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            string[] pair = part.Split('=', 2);
            string key = Uri.UnescapeDataString(pair[0]), value = pair.Length == 2 ? Uri.UnescapeDataString(pair[1]) : string.Empty;
            if (key is not ("__biz" or "mid" or "idx" or "sn" or "chksm")) continue;
            if (query.TryGetValue(key, out string? prior) && prior != value) { reason = "identity-query-conflict"; return false; }
            query[key] = value;
        }
        if (!query.TryGetValue("__biz", out biz) || !ValidBiz(biz)
            || !query.TryGetValue("mid", out string? rawMid) || rawMid.Length == 0 || !rawMid.All(char.IsAsciiDigit)
            || !long.TryParse(rawMid, NumberStyles.None, CultureInfo.InvariantCulture, out long midValue) || midValue <= 0
            || !query.TryGetValue("idx", out string? rawIdx) || rawIdx.Length == 0 || !rawIdx.All(char.IsAsciiDigit)
            || !int.TryParse(rawIdx, NumberStyles.None, CultureInfo.InvariantCulture, out idx) || idx <= 0
            || !query.TryGetValue("sn", out sn) || sn.Length is < 1 or > 256 || !sn.All(Uri.IsHexDigit))
        { reason = "identity-fields-incomplete-or-invalid"; return false; }
        if (expectedBiz is not null && expectedBiz != biz) { reason = "expected-biz-mismatch"; return false; }
        mid = midValue.ToString(CultureInfo.InvariantCulture);
        string? publicUrl = OfficialAccountArticleLinkResolver.PublicArticleUrl(url);
        if (publicUrl is null || !Uri.TryCreate(publicUrl, UriKind.Absolute, out canonical)) return false;
        // The original helper HTML-decodes its input. Its returned identity
        // must match the already validated source interpretation, including
        // optional signature fields, before any candidate is published.
        var canonicalQuery = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string part in canonical.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            string[] pair = part.Split('=', 2);
            string key = Uri.UnescapeDataString(pair[0]), value = pair.Length == 2 ? Uri.UnescapeDataString(pair[1]) : string.Empty;
            if (canonicalQuery.TryGetValue(key, out string? prior) && prior != value)
            { reason = "canonical-identity-conflict"; return false; }
            canonicalQuery[key] = value;
        }
        foreach (string key in new[] { "__biz", "mid", "idx", "sn", "chksm" })
        {
            // PublicArticleUrl omits empty optional fields; absence and empty
            // carry no signature. Any introduced or changed value is rejected.
            string expected = query.GetValueOrDefault(key) ?? string.Empty;
            string actual = canonicalQuery.GetValueOrDefault(key) ?? string.Empty;
            if (!string.Equals(expected, actual, StringComparison.Ordinal))
            { reason = "canonical-identity-conflict"; return false; }
        }
        return true;
    }
    static bool ValidEscapes(string text)
    {
        for (int i = 0; i < text.Length; i++) if (text[i] == '%')
        {
            if (i + 2 >= text.Length || !Uri.IsHexDigit(text[i + 1]) || !Uri.IsHexDigit(text[i + 2])) return false;
            i += 2;
        }
        return true;
    }
    // Charge UTF8 scalar metadata, both locators and repeated provenance per
    // candidate, plus fixed scalar/record allowance. This is not a JSON encoder.
    static long MetadataCharge(PublisherPushCandidate candidate)
    {
        long charge = 256;
        foreach (string? value in new[] { candidate.Article.Biz, candidate.Article.AppMsgId, candidate.Article.Sn, candidate.Article.Title,
            candidate.Article.ContentUrl, candidate.Article.CanonicalUrl?.AbsoluteUri, candidate.Article.AcquisitionMethod, candidate.Article.StatusDetail,
            candidate.Origin.Message.Account, candidate.Origin.Message.Chat, candidate.Origin.Message.ServerId,
            candidate.Origin.SenderUsername, candidate.DeclaredPublisherName })
        {
            if (value is null) continue;
            if (value.Length > MaximumOutputBytes) return MaximumOutputBytes + 1L;
            charge += Utf8.GetByteCount(value);
            if (charge > MaximumOutputBytes) return charge;
        }
        return charge;
    }
    static PublisherPushResult Empty(PublisherPushOutcome outcome, string detail) => new(outcome, "unsupported",
        Array.Empty<PublisherPushCandidate>(), 0, 0, 0, 0, detail);
}
