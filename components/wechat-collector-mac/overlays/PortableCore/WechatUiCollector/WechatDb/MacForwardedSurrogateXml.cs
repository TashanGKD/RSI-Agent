using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace WechatUiCollector.WechatDb;

// Presentation-only projection of adjacent surrogate numeric references. The
// original container and all stored message evidence remain unchanged.
internal static class MacForwardedSurrogateXml
{
    private const int MaximumCharacters = 16777216;
    private const char Open = '\uE000', Close = '\uE001';

    public static bool TryRead(XElement? container, out XElement? recordInfo)
    {
        recordInfo = null;
        if (container?.Name != "recorditem" || container.Nodes().Any(node => node is not XText)) return false;
        string original = container.Value;
        if (string.IsNullOrEmpty(original) || original.Length > MaximumCharacters) return false;
        try
        {
            // Literal invalid characters never qualify, including raw unpaired
            // surrogates. Only the lexical numeric-reference pair is eligible.
            XmlConvert.VerifyXmlChars(original);
            if (container.Attributes().Any(attribute => HasTransport(attribute.Name.LocalName)
                || HasTransport(attribute.Name.NamespaceName) || HasTransport(attribute.Value))) return false;
            string canonical = Scan(original, transport: false, out int pairs);
            if (pairs == 0) return false;
            var probe = ReadDocument(canonical);
            if (probe.Root?.Name != "recordinfo" || !WithinLimits(probe) || ContainsTransport(probe)) return false;

            // The disposable scalar parse proves that E000/E001 cannot come
            // from the original XML, even through numeric character references.
            // Only this independently tokenized parse may become the result.
            var projected = ReadDocument(Scan(original, transport: true, out _));
            if (projected.Root?.Name != "recordinfo" || !WithinLimits(projected)) return false;
            int converted = 0;
            // Only XText values change below. Parent structure, datatype and
            // ancestor eligibility stay fixed throughout this projection.
            var parentEligibility = new Dictionary<XElement, bool>();
            bool AllowsParent(XElement? parent)
            {
                if (parent == null) return false;
                if (!parentEligibility.TryGetValue(parent, out bool allowed))
                    parentEligibility[parent] = allowed = AllowsText(parent);
                return allowed;
            }
            foreach (var node in projected.DescendantNodes())
            {
                switch (node)
                {
                    case XElement element:
                        if (HasTransport(element.Name.LocalName) || HasTransport(element.Name.NamespaceName)
                            || element.Attributes().Any(attribute => HasTransport(attribute.Name.LocalName)
                                || HasTransport(attribute.Name.NamespaceName) || HasTransport(attribute.Value))) return false;
                        break;
                    case XText text when HasTransport(text.Value):
                        if (!AllowsParent(text.Parent) || !Restore(text.Value, out string value, ref converted)) return false;
                        text.Value = value;
                        break;
                    case XComment comment when HasTransport(comment.Value): return false;
                    case XProcessingInstruction instruction when HasTransport(instruction.Target) || HasTransport(instruction.Data): return false;
                }
            }
            if (converted == 0 || converted != pairs) return false;
            recordInfo = projected.Root;
            return true;
        }
        catch (XmlException) { return false; }
    }

    private static XDocument ReadDocument(string text)
    {
        using var reader = XmlReader.Create(new StringReader(text), new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaximumCharacters
        });
        return XDocument.Load(reader, LoadOptions.PreserveWhitespace);
    }

    private static bool HasTransport(string? value) => value?.IndexOfAny(new[] { Open, Close }) >= 0;

    private static bool ContainsTransport(XDocument document)
    {
        if (HasTransport(document.Declaration?.Version) || HasTransport(document.Declaration?.Encoding)
            || HasTransport(document.Declaration?.Standalone)) return true;
        foreach (var node in document.DescendantNodes())
        {
            if (node is XElement element && (HasTransport(element.Name.LocalName) || HasTransport(element.Name.NamespaceName)
                || element.Attributes().Any(attribute => HasTransport(attribute.Name.LocalName)
                    || HasTransport(attribute.Name.NamespaceName) || HasTransport(attribute.Value)))) return true;
            if (node is XText text && HasTransport(text.Value)) return true;
            if (node is XComment comment && HasTransport(comment.Value)) return true;
            if (node is XProcessingInstruction instruction && (HasTransport(instruction.Target) || HasTransport(instruction.Data))) return true;
        }
        return false;
    }

    private static bool WithinLimits(XDocument document)
    {
        int items = 0, recordDepth = 0;
        var ancestors = new Stack<XElement>();
        foreach (var element in document.Descendants())
        {
            // Each element enters/leaves this preorder path at most once.
            while (ancestors.TryPeek(out var previous) && !ReferenceEquals(previous, element.Parent))
                if (ancestors.Pop().Name.LocalName == "recordinfo") recordDepth--;
            if (element.Name.LocalName == "dataitem" && ++items > 500) return false;
            if (element.Name.LocalName == "recordinfo" && ++recordDepth > 5) return false;
            ancestors.Push(element);
        }
        return true;
    }

    private static bool AllowsText(XElement? element)
    {
        if (element?.Name != "datadesc" || element.Nodes().Any(node => node is not XText)) return false;
        var item = element.Parent;
        if (item?.Attribute("datatype")?.Value != "1") return false;
        for (int level = 1; level <= 5; level++)
        {
            if (item?.Name != "dataitem" || item.Parent?.Name != "datalist" || item.Parent.Parent?.Name != "recordinfo") return false;
            var record = item.Parent.Parent;
            if (record.Parent == null) return true;
            if (record.Parent.Name != "recordxml") return false;
            item = record.Parent.Parent;
            if (item?.Attribute("datatype")?.Value != "17") return false;
        }
        return false;
    }

    private static bool Restore(string text, out string value, ref int converted)
    {
        var result = new StringBuilder(text.Length);
        for (int index = 0; index < text.Length; index++)
        {
            if (text[index] == Close) { value = ""; return false; }
            if (text[index] != Open) { result.Append(text[index]); continue; }
            int end = text.IndexOf(Close, index + 1);
            if (end < 0 || !int.TryParse(text.AsSpan(index + 1, end - index - 1), NumberStyles.None,
                CultureInfo.InvariantCulture, out int scalar) || scalar < 0x10000 || scalar > 0x10FFFF)
            { value = ""; return false; }
            result.Append(char.ConvertFromUtf32(scalar)); converted++; index = end;
        }
        value = result.ToString(); return true;
    }

    // Only ordinary XML text is scanned. Markup (including quoted attributes,
    // CDATA, comments and processing instructions) is copied byte-for-character.
    private static string Scan(string text, bool transport, out int pairs)
    {
        var result = new StringBuilder(text.Length); pairs = 0;
        for (int index = 0; index < text.Length;)
        {
            if (text[index] == '<')
            {
                int end;
                string? terminator = text.AsSpan(index).StartsWith("<!--", StringComparison.Ordinal) ? "-->"
                    : text.AsSpan(index).StartsWith("<![CDATA[", StringComparison.Ordinal) ? "]]>"
                    : text.AsSpan(index).StartsWith("<?", StringComparison.Ordinal) ? "?>" : null;
                if (terminator != null)
                {
                    end = text.IndexOf(terminator, index + 2, StringComparison.Ordinal);
                    end = end < 0 ? text.Length : end + terminator.Length;
                }
                else
                {
                    char quote = '\0'; end = index + 1;
                    while (end < text.Length)
                    {
                        char current = text[end++];
                        if (quote != '\0') { if (current == quote) quote = '\0'; }
                        else if (current is '\'' or '"') quote = current;
                        else if (current == '>') break;
                    }
                }
                result.Append(text, index, end - index); index = end; continue;
            }
            if (text[index] == '&' && Reference(text, index, out int high, out int next) && high is >= 0xD800 and <= 0xDBFF
                && Reference(text, next, out int low, out int after) && low is >= 0xDC00 and <= 0xDFFF)
            {
                int scalar = 0x10000 + (high - 0xD800) * 1024 + low - 0xDC00;
                if (transport) result.Append(Open).Append(scalar.ToString(CultureInfo.InvariantCulture)).Append(Close);
                else result.Append(char.ConvertFromUtf32(scalar));
                pairs++; index = after; continue;
            }
            result.Append(text[index++]);
        }
        return result.ToString();
    }

    private static bool Reference(string text, int start, out int value, out int after)
    {
        value = 0; after = start;
        if (start + 2 >= text.Length || text[start] != '&' || text[start + 1] != '#') return false;
        int index = start + 2, radix = 10;
        if (text[index] == 'x') { radix = 16; index++; }
        int digits = 0;
        for (; index < text.Length; index++)
        {
            char current = text[index];
            if (current == ';') { after = index + 1; return digits > 0; }
            int digit = current is >= '0' and <= '9' ? current - '0'
                : radix == 16 && current is >= 'a' and <= 'f' ? current - 'a' + 10
                : radix == 16 && current is >= 'A' and <= 'F' ? current - 'A' + 10 : -1;
            if (digit < 0 || digit >= radix || value > (0x10FFFF - digit) / radix) return false;
            value = value * radix + digit; digits++;
        }
        return false;
    }
}
