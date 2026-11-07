using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace WechatUiCollector.WechatDb;

// A disposable presentation projection for one corrupt, unsupported location
// scale. It neither assigns a zoom value nor changes the stored source.
internal static class MacForwardedLocationXml
{
    private const int MaximumCharacters = 16777216;
    private const char Transport = '\uE000';

    public static bool TryRead(string text, out XElement? root)
    {
        root = null;
        if (string.IsNullOrEmpty(text) || text.Length > MaximumCharacters) return false;
        try
        {
            XmlConvert.VerifyXmlChars(text);
            // Validate the original encoding layer strictly, masking only the
            // known numeric15 reference in ordinary character data. Otherwise
            // a tolerant outer reader could also join invalid surrogate refs.
            string sourceProbe = MaskNumericFifteen(text, out int references);
            if (references != 1 || ContainsTransport(ReadDocument(sourceProbe))) return false;

            var outer = ReadDocument(text, checkCharacters: false);
            if (outer.Root?.Name != "msg") return false;
            var appMessages = outer.Root.Elements("appmsg").ToArray();
            if (appMessages.Length != 1) return false;
            var records = appMessages[0].Elements("recorditem").ToArray();
            if (records.Length != 1 || records[0].Nodes().Any(node => node is not XText)) return false;
            string originalInner = records[0].Value;

            // This copy is only a collision proof. It is never returned.
            var collisionProbe = ReadDocument(originalInner.Replace('\u000F', '\uFFFD'));
            if (collisionProbe.Root?.Name != "recordinfo" || !WithinLimits(collisionProbe)
                || ContainsTransport(collisionProbe)) return false;
            var inner = ReadDocument(originalInner.Replace('\u000F', Transport));
            if (inner.Root?.Name != "recordinfo" || !WithinLimits(inner)) return false;

            XElement? scale = null;
            foreach (var node in inner.DescendantNodes())
            {
                switch (node)
                {
                    case XElement element:
                        if (HasTransport(element.Name.LocalName) || HasTransport(element.Name.NamespaceName)
                            || element.Attributes().Any(attribute => HasTransport(attribute.Name.LocalName)
                                || HasTransport(attribute.Name.NamespaceName) || HasTransport(attribute.Value))) return false;
                        break;
                    case XText value when HasTransport(value.Value):
                        if (scale != null || value.Value != Transport.ToString()
                            || !IsTopLevelScale(value.Parent, inner.Root)) return false;
                        scale = value.Parent;
                        break;
                    case XComment comment when HasTransport(comment.Value): return false;
                    case XProcessingInstruction instruction when HasTransport(instruction.Target) || HasTransport(instruction.Data): return false;
                }
            }
            if (scale == null) return false;
            // Mutate only after traversal, so enumeration and shape checks see
            // the complete original presentation structure.
            scale.Remove();
            if (ContainsTransport(inner)) return false;
            // Keep legal declaration/comment/PI nodes outside recordinfo too;
            // the only omitted structure is the proven unsupported scale.
            records[0].Value = (inner.Declaration?.ToString() ?? "") + inner.ToString(SaveOptions.DisableFormatting);
            ValidateOuterCharacters(outer);
            if (ContainsTransport(outer)) return false;
            ReadDocument(outer.ToString(SaveOptions.DisableFormatting));
            root = outer.Root;
            return true;
        }
        catch (XmlException) { return false; }
    }

    private static XDocument ReadDocument(string text, bool checkCharacters = true)
    {
        using var reader = XmlReader.Create(new StringReader(text), new XmlReaderSettings
        {
            CheckCharacters = checkCharacters,
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaximumCharacters
        });
        return XDocument.Load(reader, LoadOptions.PreserveWhitespace);
    }

    private static bool HasTransport(string? value) => value?.IndexOf(Transport) >= 0;

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
        int items = 0, recordDepth = 0, encodedDepth = 0;
        var ancestors = new Stack<XElement>();
        var encodedRecords = new HashSet<XElement>();
        foreach (var node in document.DescendantNodes())
        {
            // Preorder traversal enters/leaves each element once, including
            // arbitrarily deep ordinary wrappers around sibling record roots.
            while (ancestors.TryPeek(out var previous) && !ReferenceEquals(previous, node.Parent))
            {
                var exited = ancestors.Pop();
                if (exited.Name.LocalName == "recordinfo") recordDepth--;
                if (encodedRecords.Contains(exited)) encodedDepth--;
            }
            if (node is XElement element)
            {
                if (element.Name.LocalName == "dataitem" && ++items > 500) return false;
                if (element.Name.LocalName == "recordinfo" && ++recordDepth > 5) return false;
                // Match the legacy first-recordxml dispatch once per item.
                // This projection supports validated inline DOM only; never
                // decode an opaque nested Value beyond these DOM budgets.
                if (element.Name == "dataitem" && int.TryParse(element.Attribute("datatype")?.Value, out int type) && type == 17
                    && element.Element("recordxml") is { } nested && nested.Element("recordinfo") == null)
                    encodedRecords.Add(nested);
                ancestors.Push(element);
                if (encodedRecords.Contains(element)) encodedDepth++;
            }
            else if (node is XText text && encodedDepth > 0 && !string.IsNullOrWhiteSpace(text.Value)) return false;
        }
        return true;
    }

    private static bool IsTopLevelScale(XElement? scale, XElement record)
    {
        if (scale?.Name != "scale" || scale.HasAttributes || scale.Value != Transport.ToString()
            || scale.Nodes().Any(node => node is not XText)) return false;
        var location = scale.Parent;
        if (location?.Name != "locitem" || location.Elements("scale").Count() != 1) return false;
        var item = location.Parent;
        return item?.Name == "dataitem" && item.Attribute("datatype")?.Value == "6"
            && item.Elements("locitem").Count() == 1 && item.Parent?.Name == "datalist"
            && ReferenceEquals(item.Parent.Parent, record);
    }

    private static void ValidateOuterCharacters(XDocument document)
    {
        if (document.Declaration is { } declaration)
        {
            XmlConvert.VerifyXmlChars(declaration.Version);
            if (declaration.Encoding != null) XmlConvert.VerifyXmlChars(declaration.Encoding);
            if (declaration.Standalone != null) XmlConvert.VerifyXmlChars(declaration.Standalone);
        }
        foreach (var node in document.DescendantNodes())
        {
            switch (node)
            {
                case XElement element:
                    XmlConvert.VerifyXmlChars(element.Name.LocalName);
                    XmlConvert.VerifyXmlChars(element.Name.NamespaceName);
                    foreach (var attribute in element.Attributes())
                    {
                        XmlConvert.VerifyXmlChars(attribute.Name.LocalName);
                        XmlConvert.VerifyXmlChars(attribute.Name.NamespaceName);
                        XmlConvert.VerifyXmlChars(attribute.Value);
                    }
                    break;
                case XText text: XmlConvert.VerifyXmlChars(text.Value); break;
                case XComment comment: XmlConvert.VerifyXmlChars(comment.Value); break;
                case XProcessingInstruction instruction:
                    XmlConvert.VerifyXmlChars(instruction.Target);
                    XmlConvert.VerifyXmlChars(instruction.Data);
                    break;
            }
        }
    }

    // A linear lexical pass used only for strict validation of a disposable
    // copy. Markup, quoted attributes, comments, CDATA and PIs stay verbatim.
    private static string MaskNumericFifteen(string text, out int references)
    {
        var result = new StringBuilder(text.Length); references = 0;
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
            if (text[index] == '&' && IsNumericFifteen(text, index, out int after))
            {
                result.Append('\uFFFD'); references++; index = after; continue;
            }
            result.Append(text[index++]);
        }
        return result.ToString();
    }

    private static bool IsNumericFifteen(string text, int start, out int after)
    {
        after = start;
        if (start + 2 >= text.Length || text[start] != '&' || text[start + 1] != '#') return false;
        int index = start + 2, radix = 10, value = 0, digits = 0;
        if (text[index] == 'x') { radix = 16; index++; }
        for (; index < text.Length; index++)
        {
            char current = text[index];
            if (current == ';') { after = index + 1; return digits > 0 && value == 15; }
            int digit = current is >= '0' and <= '9' ? current - '0'
                : radix == 16 && current is >= 'a' and <= 'f' ? current - 'a' + 10
                : radix == 16 && current is >= 'A' and <= 'F' ? current - 'A' + 10 : -1;
            if (digit < 0 || digit >= radix || value > (15 - digit) / radix) return false;
            value = value * radix + digit; digits++;
            if (value > 15) return false;
        }
        return false;
    }
}
