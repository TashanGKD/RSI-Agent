using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml;
using System.Xml.Linq;

namespace WechatUiCollector.WechatDb;

// A projection-only exception for observed Mac partial link cards. The stored XML
// remains unchanged; the caller must first attempt the original strict reader.
internal static class MacLinkCardXml
{
	private const int MaximumCharacters = 16777216;

	public static bool TryRead(string text, out XElement? root)
	{
		root = null;
		if (string.IsNullOrEmpty(text) || text.Length > MaximumCharacters) return false;
		try
		{
			// CheckCharacters=false also permits literal controls. Never accept those:
			// only the XML reader may decode a character reference into an exception.
			XmlConvert.VerifyXmlChars(text);
			using var reader = XmlReader.Create(new StringReader(text), new XmlReaderSettings
			{
				CheckCharacters = false,
				DtdProcessing = DtdProcessing.Prohibit,
				XmlResolver = null,
				MaxCharactersInDocument = MaximumCharacters
			});
			var document = XDocument.Load(reader);
			// Only XText.Value changes during this validation; parent shape,
			// datatype and ancestry remain fixed until this local cache is discarded.
			var parentEligibility = new Dictionary<XElement, bool>();
			bool AllowsParent(XElement? parent)
			{
				if (parent == null) return false;
				if (!parentEligibility.TryGetValue(parent, out bool allowed))
					parentEligibility[parent] = allowed = AllowsControlText(parent);
				return allowed;
			}
			bool repaired = false;
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
				case XText value:
					try { XmlConvert.VerifyXmlChars(value.Value); }
					catch (XmlException)
					{
						if (!AllowsParent(value.Parent)) return false;
						var characters = value.Value.ToCharArray();
						for (int i = 0; i < characters.Length; i++)
						{
							if (characters[i] is '\u0001' or '\u0002' or '\u0003' or '\u001D')
							{
								characters[i] = '\uFFFD';
								repaired = true;
							}
						}
						string projection = new string(characters);
						XmlConvert.VerifyXmlChars(projection); // Reject any other invalid code.
						value.Value = projection;
					}
					break;
				case XComment comment:
					XmlConvert.VerifyXmlChars(comment.Value);
					break;
				case XProcessingInstruction instruction:
					XmlConvert.VerifyXmlChars(instruction.Target);
					XmlConvert.VerifyXmlChars(instruction.Data);
					break;
				}
			}
			if (!repaired) return false;
			root = document.Root;
			return root != null;
		}
		catch (XmlException) { return false; }
	}

	private static bool AllowsControlText(XElement? element)
	{
		if (element == null || element.HasElements) return false;
		var path = element.AncestorsAndSelf().Reverse().ToArray();
		if (path.Any(part => part.Name.NamespaceName.Length != 0)) return false;
		return (path.Length == 3 && path[0].Name == "msg" && path[1].Name == "appmsg"
			&& (path[2].Name == "title" || path[2].Name == "des"))
			|| (path.Length == 4 && path[0].Name == "msg" && path[1].Name == "appmsg"
			&& path[2].Name == "appattach" && path[3].Name == "encryver");
	}
}
