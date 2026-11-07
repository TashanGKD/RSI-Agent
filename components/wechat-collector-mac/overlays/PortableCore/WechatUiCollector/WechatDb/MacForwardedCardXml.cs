using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml;
using System.Xml.Linq;

namespace WechatUiCollector.WechatDb;

// Presentation-only recovery for the observed Mac partial forwarded-text case.
// The caller must try strict XML first; stored content and resource values are
// never changed. Any invalid character outside the exact text paths rejects it.
internal static class MacForwardedCardXml
{
	private const int MaximumCharacters = 16777216;
	private const int MaximumRecordLevels = 5;
	private const int MaximumItems = 500;

	public static bool TryRead(string text, out XElement? root)
	{
		root = null;
		if (string.IsNullOrEmpty(text) || text.Length > MaximumCharacters) return false;
		try
		{
			// Only numeric references in the original XML may supply the observed
			// controls. The tolerant reader must never admit literal raw controls.
			XmlConvert.VerifyXmlChars(text);
			var outer = ReadDocument(text);
			if (outer.Root?.Name != "msg") return false;
			var appMessages = outer.Root.Elements("appmsg").ToArray();
			if (appMessages.Length != 1) return false;
			var records = appMessages[0].Elements("recorditem").ToArray();
			if (records.Length != 1 || records[0].Nodes().Any(node => node is not XText)) return false;
			string innerText = records[0].Value;
			// .NET's reader still rejects literal controls with CheckCharacters=false.
			// A disposable, bounded parse proves the fixed transport characters are
			// absent, including characters supplied by numeric references. This copy
			// is used only for collision detection and is never returned.
			var collisionProbe = ReadDocument(innerText.Replace('\u0008', '\uFFFD').Replace('\u0014', '\uFFFD'));
			if (ContainsTransport(collisionProbe)) return false;
			var inner = ReadDocument(innerText.Replace('\u0008', '\uE000').Replace('\u0014', '\uE001'));
			if (inner.Root?.Name != "recordinfo") return false;
			bool repaired = false;
			if (!Validate(inner, allowTextRepair: true, ref repaired) || !repaired) return false;
			records[0].Value = inner.ToString(SaveOptions.DisableFormatting);
			if (!Validate(outer, allowTextRepair: false, ref repaired)) return false;
			root = outer.Root;
			return true;
		}
		catch (XmlException) { return false; }
	}

	private static XDocument ReadDocument(string text)
	{
		using var reader = XmlReader.Create(new StringReader(text), new XmlReaderSettings
		{
			CheckCharacters = false,
			DtdProcessing = DtdProcessing.Prohibit,
			XmlResolver = null,
			MaxCharactersInDocument = MaximumCharacters
		});
		return XDocument.Load(reader, LoadOptions.PreserveWhitespace);
	}

	private static string RestoreTransport(string value) => value.Replace('\uE000', '\u0008').Replace('\uE001', '\u0014');
	private static bool HasTransport(string? value) => value?.IndexOfAny(new[] { '\uE000', '\uE001' }) >= 0;

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

	private static bool Validate(XDocument document, bool allowTextRepair, ref bool repaired)
	{
		// Only XText.Value changes during this validation; parent shape,
		// datatype and ancestry remain fixed until this local cache is discarded.
		var parentEligibility = new Dictionary<XElement, bool>();
		bool AllowsParent(XElement? parent)
		{
			if (parent == null) return false;
			if (!parentEligibility.TryGetValue(parent, out bool allowed))
				parentEligibility[parent] = allowed = AllowsText(parent);
			return allowed;
		}
		int items = 0, recordDepth = 0;
		var ancestors = new Stack<XElement>();
		foreach (var node in document.DescendantNodes())
		{
			switch (node)
			{
			case XElement element:
				// Never construct an invalid XName while restoring transport. Invalid
				// names/namespaces are rejected instead; only text nodes may be repaired.
				if (allowTextRepair && (HasTransport(element.Name.LocalName) || HasTransport(element.Name.NamespaceName))) return false;
				XmlConvert.VerifyXmlChars(element.Name.LocalName);
				XmlConvert.VerifyXmlChars(element.Name.NamespaceName);
				foreach (var attribute in element.Attributes())
				{
					if (allowTextRepair && (HasTransport(attribute.Name.LocalName) || HasTransport(attribute.Name.NamespaceName))) return false;
					XmlConvert.VerifyXmlChars(attribute.Name.LocalName);
					XmlConvert.VerifyXmlChars(attribute.Name.NamespaceName);
					XmlConvert.VerifyXmlChars(allowTextRepair ? RestoreTransport(attribute.Value) : attribute.Value);
				}
				if (allowTextRepair)
				{
					// Maintain the preorder path instead of walking all ordinary
					// wrapper ancestors again for every sibling recordinfo.
					while (ancestors.TryPeek(out var previous) && !ReferenceEquals(previous, element.Parent))
						if (ancestors.Pop().Name.LocalName == "recordinfo") recordDepth--;
					if (element.Name.LocalName == "dataitem" && ++items > MaximumItems) return false;
					if (element.Name.LocalName == "recordinfo" && ++recordDepth > MaximumRecordLevels) return false;
					ancestors.Push(element);
				}
				break;
			case XText value:
				if (allowTextRepair) value.Value = RestoreTransport(value.Value);
				try { XmlConvert.VerifyXmlChars(value.Value); }
				catch (XmlException)
				{
					if (!allowTextRepair || !AllowsParent(value.Parent)) return false;
					string projection = value.Value.Replace('\u0008', '\uFFFD').Replace('\u0014', '\uFFFD');
					XmlConvert.VerifyXmlChars(projection); // Any other invalid code rejects the entire projection.
					if (projection != value.Value) repaired = true;
					value.Value = projection;
				}
				break;
			case XComment comment:
				XmlConvert.VerifyXmlChars(allowTextRepair ? RestoreTransport(comment.Value) : comment.Value);
				break;
			case XProcessingInstruction instruction:
				XmlConvert.VerifyXmlChars(allowTextRepair ? RestoreTransport(instruction.Target) : instruction.Target);
				XmlConvert.VerifyXmlChars(allowTextRepair ? RestoreTransport(instruction.Data) : instruction.Data);
				break;
			}
		}
		return true;
	}

	private static bool AllowsText(XElement? element)
	{
		if (element?.Name != "datadesc" || element.Nodes().Any(node => node is not XText)) return false;
		var item = element.Parent;
		if (item?.Attribute("datatype")?.Value is not ("1" or "17")) return false;
		for (int level = 1; level <= MaximumRecordLevels; level++)
		{
			if (item?.Name != "dataitem" || item.Parent?.Name != "datalist"
				|| item.Parent.Parent?.Name != "recordinfo") return false;
			var record = item.Parent.Parent;
			if (record.Parent == null) return true;
			if (record.Parent.Name != "recordxml") return false;
			item = record.Parent.Parent;
			if (item?.Attribute("datatype")?.Value != "17") return false;
		}
		return false;
	}
}
