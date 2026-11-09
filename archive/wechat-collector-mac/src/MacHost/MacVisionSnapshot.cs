using System.Text.Json.Serialization;

namespace WechatCollector.Mac;

public sealed record MacVisionRect(double X, double Y, double Width, double Height)
{
    [JsonIgnore] public double Right => X + Width;
    [JsonIgnore] public double Bottom => Y + Height;
    [JsonIgnore] public bool Finite => double.IsFinite(X) && double.IsFinite(Y) && double.IsFinite(Width) && double.IsFinite(Height);
    public bool Contains(MacVisionRect other) => other.X >= X && other.Y >= Y && other.Right <= Right && other.Bottom <= Bottom;
    public bool Intersects(MacVisionRect other) => other.X < Right && other.Right > X && other.Y < Bottom && other.Bottom > Y;
}
public sealed record MacVisionWindow(long Id, int Pid, string OwnerBundleId, string? AppVersion, double ProcessLaunchTime, MacVisionRect PointBounds);
public sealed record MacVisionImage(int Width, int Height, string Sha256);
public sealed record MacVisionPermission(bool ScreenCapture, bool Accessibility, bool EventPosting);
public sealed record MacVisionWord(string Text, double Confidence, MacVisionRect Bounds);
public sealed record MacVisionRectangle(double Confidence, MacVisionRect Bounds, string Source);
public sealed record MacVisionUncertainRegion(MacVisionRect Bounds, double Confidence, string? Reason);
public sealed record MacVisionSnapshot(int SchemaVersion, string Status, string CoordinateSpace, string ConfidenceScope, string MessageImport,
    MacVisionWindow? Window, MacVisionImage? Image, MacVisionPermission? Permission,
    IReadOnlyList<MacVisionWord>? Words, IReadOnlyList<MacVisionRectangle>? Rectangles, IReadOnlyList<MacVisionUncertainRegion>? UncertainRegions, string? Code = null, string? OcclusionStatus = null);
public sealed record MacVisionFrameIdentity(long WindowId, int Pid, string OwnerBundleId, string? AppVersion, double ProcessLaunchTime, MacVisionRect PointBounds, int ImageWidth, int ImageHeight);
public sealed record MacVisionLabelCandidate(string Text, double Confidence, MacVisionRect Bounds, bool Truncated, bool Duplicate, string Evidence = "ocr_label_candidate");
public sealed record MacVisionNavigationDecision(bool CanAct, string Code, string LayoutStatus, string? CurrentTitle,
    IReadOnlyList<MacVisionLabelCandidate> VisibleCandidates, MacVisionRect? SafeScrollRegion,
    string MessageImport = "not_performed", string FingerprintMeaning = "frame_only_not_scroll_or_history_completion",
    MacVisionFrameIdentity? Frame = null, string? ImageSha256 = null, string? LayoutProfileId = null, bool ExecutionPerformed = false);

// This is not a helper/wire DTO. Only trusted host-side profile validation may
// construct it; raw OCR JSON cannot grant itself layout-verification authority.
public sealed class MacVisionVerifiedLayout
{
    internal MacVisionVerifiedLayout(string profileId, MacVisionFrameIdentity frame, string imageSha256,
        MacVisionRect headerRegion, MacVisionRect sidebarRegion, MacVisionRect inputBounds, MacVisionRect sendAnchorRegion,
        int inputRectangleIndex, int sendWordIndex)
    {
        ProfileId = profileId; Frame = frame; ImageSha256 = imageSha256; HeaderRegion = headerRegion; SidebarRegion = sidebarRegion;
        InputBounds = inputBounds; SendAnchorRegion = sendAnchorRegion; InputRectangleIndex = inputRectangleIndex; SendWordIndex = sendWordIndex;
    }
    public string ProfileId { get; }
    public MacVisionFrameIdentity Frame { get; }
    public string ImageSha256 { get; }
    public MacVisionRect HeaderRegion { get; }
    public MacVisionRect SidebarRegion { get; }
    public MacVisionRect InputBounds { get; }
    public MacVisionRect SendAnchorRegion { get; }
    public int InputRectangleIndex { get; }
    public int SendWordIndex { get; }
}
