using System.Text;
using System.Text.Json;

namespace WechatCollector.Mac;

// Pure interpretation only. This type has no capture, input, store or message
// import dependencies. A positive decision is snapshot-bound evidence, not an
// executed action, successful scroll or history-completeness assertion.
public static class MacVisionNavigation
{
    const double NameConfidence = .97, RectangleConfidence = .90, SafetyMargin = 16;
    static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { PropertyNameCaseInsensitive = false, MaxDepth = 16 };
    public static MacVisionSnapshot ParseSnapshot(string json)
    {
        if (json is null || json.Length > 2 * 1024 * 1024) throw new ArgumentException("Vision snapshot is missing or oversized.");
        try
        {
            using var document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 });
            if (document.RootElement.ValueKind != JsonValueKind.Object) throw new ArgumentException("Vision snapshot must be an object.");
            RejectDuplicateProperties(document.RootElement);
            return JsonSerializer.Deserialize<MacVisionSnapshot>(json, JsonOptions) ?? throw new ArgumentException("Vision snapshot is empty.");
        }
        catch (JsonException error) { throw new ArgumentException("Vision snapshot JSON is invalid.", error); }
    }
    static void RejectDuplicateProperties(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var property in value.EnumerateObject())
            {
                if (!names.Add(property.Name)) throw new ArgumentException("Vision snapshot contains duplicate properties.");
                RejectDuplicateProperties(property.Value);
            }
        }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) RejectDuplicateProperties(item);
    }
    public static MacVisionFrameIdentity CaptureIdentity(MacVisionSnapshot snapshot)
    {
        if (!ValidSnapshot(snapshot)) throw new ArgumentException("Vision snapshot has invalid frame evidence.");
        var window = snapshot.Window!; var image = snapshot.Image!;
        return new(window.Id, window.Pid, window.OwnerBundleId, window.AppVersion, window.ProcessLaunchTime, window.PointBounds, image.Width, image.Height);
    }
    public static MacVisionNavigationDecision ReadOnly(MacVisionSnapshot snapshot)
    {
        if (!ValidSnapshot(snapshot) || snapshot.Status is not ("ocr_ready" or "ocr_empty")) return Block("snapshot_unavailable", [], null);
        if (!Supported(snapshot)) return Block("unsupported_contract", [], null);
        if (snapshot.Window!.OwnerBundleId != "com.tencent.xinWeChat") return Block("window_not_wechat", [], null);
        var image = snapshot.Image!;
        // These are explicitly uncertain display candidates, never a layout proof.
        var header = new MacVisionRect(image.Width * .30, 0, image.Width * .70, image.Height * .15);
        var sidebar = new MacVisionRect(image.Width * .05, image.Height * .15, image.Width * .25, image.Height * .70);
        var names = Labels(snapshot, sidebar); var titles = Labels(snapshot, header);
        return Block("input_boundary_unverified", names, SingleTitle(titles));
    }
    public static MacVisionNavigationDecision Assess(MacVisionSnapshot snapshot, MacVisionFrameIdentity expectedWindow,
        string targetLabel, int knownTargetIdentityCount, MacVisionVerifiedLayout? layout)
    {
        if (!ValidSnapshot(snapshot)) return Block("invalid_snapshot", [], null);
        if (snapshot.Status != "ocr_ready" || !string.IsNullOrEmpty(snapshot.Code)) return Block("snapshot_unavailable", [], null);
        if (!Supported(snapshot))
            return Block("unsupported_contract", [], null);
        if (snapshot.Window!.OwnerBundleId != "com.tencent.xinWeChat" || CaptureIdentity(snapshot) != expectedWindow) return Block("window_changed", [], null);
        if (snapshot.Permission is not { ScreenCapture: true, Accessibility: true, EventPosting: true }) return Block("permission_unavailable", [], null);
        if (layout is null) return ReadOnly(snapshot);
        // Window-only OCR is usable for observation while obscured. Any action
        // additionally needs explicit clear evidence and a fresh native recheck
        // immediately before execution; this snapshot alone cannot execute it.
        if (snapshot.OcclusionStatus != "clear") return Block("occlusion_unverified", [], null);
        if (string.IsNullOrWhiteSpace(layout.ProfileId) || string.IsNullOrWhiteSpace(snapshot.Window.AppVersion) || snapshot.Window.AppVersion == "unknown" || layout.Frame != expectedWindow || !string.Equals(layout.ImageSha256, snapshot.Image!.Sha256, StringComparison.OrdinalIgnoreCase))
            return Block("layout_snapshot_mismatch", [], null);
        if (!ValidLayout(snapshot, layout)) return Block("input_boundary_unverified", [], null);
        var names = Labels(snapshot, layout.SidebarRegion, layout.InputBounds, layout.SendAnchorRegion);
        var titles = Labels(snapshot, layout.HeaderRegion, layout.InputBounds, layout.SendAnchorRegion);
        var title = SingleTitle(titles);
        if (HasCriticalUncertainty(snapshot, layout)) return Block("critical_region_uncertain", names, title);
        if (!VerifiedSendAnchor(snapshot, layout)) return Block("send_anchor_unverified", names, title);
        if (knownTargetIdentityCount != 1) return Block("ambiguous_database_target", names, title);
        var target = Normalize(targetLabel);
        if (target.Length == 0 || HasEllipsis(target)) return Block("truncated_name", names, title);
        if (titles.Count != 1) return Block("ambiguous_title", names, title);
        if (titles[0].Confidence < NameConfidence) return Block("low_confidence_title", names, null);
        if (titles[0].Truncated) return Block("truncated_name", names, null);
        if (titles[0].Text != target) return Block("target_not_confirmed", names, title);
        var matches = names.Where(name => name.Text == target).ToArray();
        if (matches.Length > 1) return Block("duplicate_name", names, title);
        if (matches.Any(name => name.Confidence < NameConfidence || name.Truncated)) return Block("uncertain_visible_target", names, title);
        double left = Math.Max(layout.InputBounds.X, layout.HeaderRegion.X) + SafetyMargin;
        double right = Math.Min(layout.InputBounds.Right, layout.HeaderRegion.Right) - SafetyMargin;
        double top = layout.HeaderRegion.Bottom + SafetyMargin;
        double bottom = Math.Min(layout.InputBounds.Y, layout.SendAnchorRegion.Y) - SafetyMargin;
        var scroll = new MacVisionRect(left, top, right - left, bottom - top);
        if (!InImage(scroll, snapshot.Image!) || scroll.Width < 100 || scroll.Height < 100 || scroll.Intersects(layout.InputBounds) || scroll.Intersects(layout.SendAnchorRegion) || scroll.Intersects(layout.SidebarRegion))
            return Block("safe_scroll_region_unavailable", names, title);
        return new(true, "snapshot_target_confirmed", "verified_profile", title, names, scroll, Frame: expectedWindow, ImageSha256: snapshot.Image.Sha256, LayoutProfileId: layout.ProfileId);
    }
    static bool Supported(MacVisionSnapshot snapshot) => snapshot.SchemaVersion == 1 && snapshot.CoordinateSpace == "window_pixels_top_left" && snapshot.ConfidenceScope == "line_candidate" && snapshot.MessageImport == "not_performed";
    static MacVisionNavigationDecision Block(string code, IReadOnlyList<MacVisionLabelCandidate> names, string? title) => new(false, code, "unknown", title, names, null);
    static string Normalize(string? value) => (value ?? "").Trim().Normalize(NormalizationForm.FormC);
    static bool HasEllipsis(string text) => text.Contains('…') || text.Contains("...", StringComparison.Ordinal) || text.Contains('\n') || text.Contains('\r');
    static string? SingleTitle(IReadOnlyList<MacVisionLabelCandidate> titles) => titles.Count == 1 && titles[0].Confidence >= NameConfidence && !titles[0].Truncated ? titles[0].Text : null;
    static IReadOnlyList<MacVisionLabelCandidate> Labels(MacVisionSnapshot snapshot, MacVisionRect region, params MacVisionRect[] excluded)
    {
        var items = snapshot.Words!.Where(word => region.Contains(word.Bounds) && !excluded.Any(area => area.Intersects(word.Bounds)) && !string.IsNullOrWhiteSpace(word.Text)).ToArray();
        var counts = items.GroupBy(word => Normalize(word.Text), StringComparer.Ordinal).ToDictionary(group => group.Key, group => group.Count(), StringComparer.Ordinal);
        double inset = Math.Max(8, snapshot.Image!.Width * .006);
        return items.Select(word => new MacVisionLabelCandidate(Normalize(word.Text), word.Confidence, word.Bounds,
            HasEllipsis(word.Text) || word.Bounds.Right >= region.Right - inset || word.Bounds.Bottom >= region.Bottom - 4 || word.Bounds.X <= region.X + 2 || word.Bounds.Y <= region.Y + 2,
            counts[Normalize(word.Text)] > 1)).ToArray();
    }
    static bool ValidSnapshot(MacVisionSnapshot? snapshot)
    {
        if (snapshot?.Window is not { } window || snapshot.Image is not { } image || snapshot.Words is null || snapshot.Rectangles is null || snapshot.UncertainRegions is null) return false;
        if (window.Id is <= 0 or > uint.MaxValue || window.Pid <= 0 || string.IsNullOrWhiteSpace(window.OwnerBundleId) || window.OwnerBundleId.Length > 256 || window.AppVersion?.Length > 64 || !double.IsFinite(window.ProcessLaunchTime) || window.ProcessLaunchTime <= 0 || !Positive(window.PointBounds)) return false;
        if (image.Width is < 100 or > 16384 || image.Height is < 100 or > 16384 || !Hash(image.Sha256)) return false;
        double scaleX = image.Width / window.PointBounds.Width, scaleY = image.Height / window.PointBounds.Height;
        if (scaleX is < .5 or > 4 || scaleY is < .5 or > 4 || Math.Abs(scaleX - scaleY) > .05) return false;
        if (snapshot.Words.Count > 2048 || snapshot.Rectangles.Count > 512 || snapshot.UncertainRegions.Count > 2048) return false;
        return snapshot.Words.All(word => word is not null && word.Text is not null && word.Text.Length <= 1024 && Confidence(word.Confidence) && InImage(word.Bounds, image))
            && snapshot.Rectangles.All(rectangle => rectangle is not null && Confidence(rectangle.Confidence) && InImage(rectangle.Bounds, image))
            && snapshot.UncertainRegions.All(region => region is not null && Confidence(region.Confidence) && InImage(region.Bounds, image));
    }
    static bool ValidLayout(MacVisionSnapshot snapshot, MacVisionVerifiedLayout layout)
    {
        var image = snapshot.Image!;
        var input = layout.InputBounds; var send = layout.SendAnchorRegion;
        if (new[] { input, send, layout.HeaderRegion, layout.SidebarRegion }.Any(region => !InImage(region, image))) return false;
        if (input.X < image.Width * .20 || input.Y < image.Height * .50 || input.Width < image.Width * .25 || input.Height < 20 || send.Intersects(input)) return false;
        if (send.Y < input.Bottom || send.Y - input.Bottom > image.Height * .10 || send.X < input.X + input.Width * .60 || send.Right > input.Right + 2) return false;
        if (layout.HeaderRegion.Bottom + SafetyMargin * 2 >= input.Y || layout.SidebarRegion.Right > input.X || layout.SidebarRegion.Intersects(layout.HeaderRegion) || layout.HeaderRegion.Intersects(send)) return false;
        if (layout.InputRectangleIndex == -1) return true; // Independently verified host profile; never inferred from raw rectangles.
        if (layout.InputRectangleIndex < 0 || layout.InputRectangleIndex >= snapshot.Rectangles!.Count) return false;
        var observation = snapshot.Rectangles[layout.InputRectangleIndex];
        return observation.Source == "VNDetectRectangles" && observation.Confidence >= RectangleConfidence && SameEdges(observation.Bounds, input, 2);
    }
    static bool VerifiedSendAnchor(MacVisionSnapshot snapshot, MacVisionVerifiedLayout layout)
    {
        if (layout.SendWordIndex < 0 || layout.SendWordIndex >= snapshot.Words!.Count) return false;
        var matches = snapshot.Words.Select((word, index) => (word, index)).Where(pair => layout.SendAnchorRegion.Contains(pair.word.Bounds) && (pair.word.Text.Trim() is "发送" or "Send")).ToArray();
        return matches.Length == 1 && matches[0].index == layout.SendWordIndex && matches[0].word.Confidence >= NameConfidence && !layout.InputBounds.Intersects(matches[0].word.Bounds);
    }
    static bool HasCriticalUncertainty(MacVisionSnapshot snapshot, MacVisionVerifiedLayout layout)
    {
        var input = layout.InputBounds;
        var edges = new[] { new MacVisionRect(input.X - 8, input.Y - 8, input.Width + 16, 16), new MacVisionRect(input.X - 8, input.Bottom - 8, input.Width + 16, 16), new MacVisionRect(input.X - 8, input.Y, 16, input.Height), new MacVisionRect(input.Right - 8, input.Y, 16, input.Height) };
        var uncertain = snapshot.UncertainRegions!.Select(region => region.Bounds).Concat(snapshot.Words!.Where(word => word.Confidence < NameConfidence || string.IsNullOrWhiteSpace(word.Text)).Select(word => word.Bounds));
        return uncertain.Any(bounds => layout.HeaderRegion.Intersects(bounds) || layout.SidebarRegion.Intersects(bounds) || layout.SendAnchorRegion.Intersects(bounds) || edges.Any(edge => edge.Intersects(bounds)));
    }
    static bool Confidence(double value) => double.IsFinite(value) && value is >= 0 and <= 1;
    static bool Hash(string? value) => value is { Length: 64 } && value.All(Uri.IsHexDigit);
    static bool Positive(MacVisionRect? rectangle) => rectangle is { Finite: true, Width: > 0, Height: > 0 };
    static bool InImage(MacVisionRect? rectangle, MacVisionImage image) => Positive(rectangle) && rectangle!.X >= 0 && rectangle.Y >= 0 && rectangle.Right <= image.Width && rectangle.Bottom <= image.Height;
    static bool SameEdges(MacVisionRect first, MacVisionRect second, double tolerance) => Math.Abs(first.X - second.X) <= tolerance && Math.Abs(first.Y - second.Y) <= tolerance && Math.Abs(first.Right - second.Right) <= tolerance && Math.Abs(first.Bottom - second.Bottom) <= tolerance;
}
