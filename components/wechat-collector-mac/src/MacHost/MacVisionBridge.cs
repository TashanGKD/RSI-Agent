using WechatUiCollector.Diagnostics;
namespace WechatCollector.Mac;
public sealed partial class MacController
{
    // Called only by the launch-authenticated native parent. OCR stays in memory;
    // return a content-free status to the setup window, never a transcript.
    public async Task<object> ReadVisionStatusAsync(string json, CancellationToken token)
    {
        using var requestLifetime = CancellationTokenSource.CreateLinkedTokenSource(token, LifetimeToken);
        token = requestLifetime.Token;
        var snapshot = MacVisionNavigation.ParseSnapshot(json);
        if (snapshot.Status is not ("ocr_ready" or "ocr_empty") || snapshot.Window is null)
            return new { status = "blocked", message = "微信窗口读取未完成，请重新检查权限和窗口。", importedMessages = 0 };
        var decision = MacVisionNavigation.ReadOnly(snapshot);
        if (decision.Code != "input_boundary_unverified") return new { status = "blocked", message = "窗口识别证据不完整，未执行自动操作。", importedMessages = 0 };
        RuntimeEventSource.Emit(AppLogLevel.Information,"MAC_WINDOW_READ_OBSERVED","MacVisionBridge","本机微信窗口识别证据已收到。",new Dictionary<string,object?>{["wordCount"]=snapshot.Words?.Count??0,["screenCapture"]=snapshot.Permission?.ScreenCapture,["accessibility"]=snapshot.Permission?.Accessibility,["eventPosting"]=snapshot.Permission?.EventPosting,["occlusionStatus"]=snapshot.OcclusionStatus});
        string expectedAccount;
        await gate.WaitAsync(token);
        try { expectedAccount = account; } finally { gate.Release(); }
        var matches = await MacActiveAccountProbe.MatchesAsync(snapshot.Window.Pid, snapshot.Window.ProcessLaunchTime, expectedAccount, token);
        await gate.WaitAsync(token);
        try { matches &= expectedAccount.Length > 0 && account == expectedAccount; } finally { gate.Release(); }
        if (!matches) return new { status = "blocked", message = "当前微信账号与所选记录账号尚未唯一对应，已停止自动操作。", importedMessages = 0 };
        RuntimeEventSource.Emit(AppLogLevel.Information,"MAC_WINDOW_ACCOUNT_BINDING_PASSED","MacVisionBridge","微信窗口进程与所选本地账号对应校验通过。");
        if (snapshot.Status == "ocr_empty" || snapshot.Words?.Count == 0) return new { status = "blocked", message = "微信窗口账号核对通过，但没有识别到可靠文字；未启用自动操作。", importedMessages = 0 };
        return new { status = "read_only", message = $"已完成微信窗口本地识别（{snapshot.Words?.Count ?? 0} 个文字区域）。账号核对通过；输入区布局仍待验证，自动操作暂未启用。", importedMessages = 0, layoutStatus = decision.LayoutStatus, canAct = false };
    }
}
