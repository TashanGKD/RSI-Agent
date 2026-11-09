using System.Text.Json;
using System.Text.RegularExpressions;
using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.Storage;

namespace WechatCollector.Mac;

// Request id is a public hint. Account, nonce and liveness come only from protected Native HTTP.
public sealed class MacConnectionPending(string account, string operation)
{
    readonly object mutex = new();
    bool claimed, dispatched, revoked, terminal, stopped;
    MacConnectionSettlement? workerSettlement;
    public TaskCompletionSource ReleaseSettled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public void PublishSettlement(MacConnectionSettlement value) { lock (mutex) {
        if (value.Account != Account || value.Operation != Operation || value.Cleanup is not ("complete" or "unconfirmed")) throw new ArgumentException("连接清理身份无效。");
        if (workerSettlement is not null && workerSettlement != value) throw new InvalidOperationException("Immutable cleanup settlement changed.");
        workerSettlement ??= value;
    } }
    string? failureCode;
    static readonly HashSet<string> FailureCodes = ["ownerInvalid", "managedBundleInvalid", "signatureInvalid", "existingApplication", "launchFailed", "launchDeadline", "identityChanged", "stopDeadline", "bootstrapFailed", "originalHandoverFailed"];
    public string? FailureCode { get { lock (mutex) return failureCode; } }
    public string RequestId { get; } = Guid.NewGuid().ToString("N");
    public string Account { get; } = account;
    public string Operation { get; } = operation;
    public TaskCompletionSource StopSettled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public bool WasClaimed { get { lock (mutex) return claimed; } }
    public bool Revoked { get { lock (mutex) return revoked; } }
    public bool Terminal { get { lock (mutex) return terminal; } }
    public void Revoke() { lock (mutex) revoked = true; }
    public void Finish() { lock (mutex) terminal = true; }
    public object Snapshot() { lock (mutex) return new { requestId = RequestId, account = Account, operation = Operation, state = revoked || terminal ? "stop" : "active" }; }
    public object Handle(string raw)
    {
        if (System.Text.Encoding.UTF8.GetByteCount(raw) > 4096) throw new ArgumentException("连接请求无效。");
        using var doc = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 4 }); var c = doc.RootElement;
        if (c.ValueKind != JsonValueKind.Object) throw new ArgumentException("连接请求无效。");
        var properties = c.EnumerateObject().ToArray();
        if (properties.Select(p => p.Name).Distinct().Count() != properties.Length) throw new ArgumentException("连接请求无效。");
        string Text(string key) => c.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
        string action = Text("action"); var names = action == "claim" ? new[] { "action", "requestId" } : action == "failure" ? new[] { "action", "requestId", "account", "operation", "code" } : new[] { "action", "requestId", "account", "operation" };
        if (properties.Length != names.Length || properties.Any(p => !names.Contains(p.Name)) || Text("requestId") != RequestId) throw new ArgumentException("连接请求已过期。");
        if (action == "failure" && !FailureCodes.Contains(Text("code"))) throw new ArgumentException("连接请求无效。");
        lock (mutex)
        {
            if (action == "claim")
            {
                if (claimed || revoked || terminal) throw new ArgumentException("连接请求已过期。"); claimed = true;
            }
            else
            {
                if (!claimed || Text("account") != Account || Text("operation") != Operation || stopped && action is not ("stopped" or "cleanup" or "released")) throw new ArgumentException("连接请求已过期。");
                switch (action)
                {
                    case "dispatch": if (revoked || terminal || dispatched) throw new ArgumentException("连接请求已过期。"); dispatched = true; break;
                    case "cancel": if (revoked) throw new ArgumentException("连接请求已取消。"); revoked = true; break;
                    case "failure": if (revoked || terminal || failureCode is not null) throw new ArgumentException("连接请求已过期。"); failureCode = Text("code"); revoked = true; break;
                    case "status": break;
                    case "cleanup": return new { requestId = RequestId, account = Account, operation = Operation, state = revoked || terminal ? "stop" : "active", cleanup = !stopped || workerSettlement is null ? "pending" : workerSettlement.Cleanup };
                    case "released":
                        if (!stopped || workerSettlement is null) throw new ArgumentException("连接清理尚未确认。");
                        ReleaseSettled.TrySetResult(); break;
                    case "stopped": if (!terminal && !revoked) throw new ArgumentException("连接仍在处理。"); stopped = true; StopSettled.TrySetResult(); break;
                    default: throw new ArgumentException("连接请求无效。");
                }
            }
            return new { requestId = RequestId, account = Account, operation = Operation, state = revoked || terminal ? "stop" : "active" };
        }
    }
}

public sealed partial class MacController
{
    readonly object connectionMutex = new();
    // Private in-process fixture boundary; no command, environment, or HTTP field selects authority.
    Func<string> connectionHomeLookup = MacConnectionOwner.Home;
    MacConnectionPending? connectionPending;
    // One retained operation: its worker cleanup fact is immutable; readback grants no new work.
    MacConnectionPending? connectionTombstone;
    bool connectionRecoveryRequired;
    bool ConnectionRecoveryRequired { get { lock (connectionMutex) return connectionRecoveryRequired; } }
    bool ConnectionImportBlocked { get { lock (connectionMutex) return connectionRecoveryRequired || connectionPending is { } pending && !pending.ReleaseSettled.Task.IsCompleted || connectionTombstone is { } retained && !retained.ReleaseSettled.Task.IsCompleted; } }
    const string ConnectionRecoveryMessage = "本机连接的清理尚未确认，新连接和导入已暂停；已保存记录仍可查看。";
    MacConnectionWorker? connectionWorker;
    CancellationTokenSource? connectionCancellation;
    public async Task<object> NativeConnectionAsync(string raw, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (System.Text.Encoding.UTF8.GetByteCount(raw) > 4096) throw new ArgumentException("连接请求无效。");
        MacConnectionPending pending; MacConnectionWorker worker; CancellationTokenSource cancellation;
        lock (connectionMutex)
        {
            using var message = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 4 });
            if (message.RootElement.ValueKind != JsonValueKind.Object) throw new ArgumentException("连接请求无效。");
            string? requested = message.RootElement.TryGetProperty("action", out var requestedValue) && requestedValue.ValueKind == JsonValueKind.String ? requestedValue.GetString() : null;
            if (requested is "cleanup" or "released" && connectionPending is null && connectionTombstone is { } retained)
                return retained.Handle(raw);
            pending = connectionPending ?? throw new ArgumentException("连接请求已过期。");
            worker = connectionWorker ?? throw new ArgumentException("连接请求已过期。");
            cancellation = connectionCancellation ?? throw new ArgumentException("连接请求已过期。");
        }
        if (cancellation.IsCancellationRequested) pending.Revoke();
        object response = pending.Handle(raw);
        using var doc = JsonDocument.Parse(raw); string action = doc.RootElement.GetProperty("action").GetString()!;
        if (action is "cancel" or "failure") { cancellation.Cancel(); worker.Revoke(); }
        if (action == "dispatch")
        {
            try { await worker.SendStartAsync(pending.Account, pending.Operation); }
            catch { pending.Revoke(); cancellation.Cancel(); throw new ArgumentException("连接请求已过期。"); }
        }
        if (cancellation.IsCancellationRequested) pending.Revoke();
        return action == "cleanup" ? response : pending.Snapshot();
    }
    async Task AwaitConnectionStopAsync(MacConnectionPending pending, CancellationToken token)
    {
        try { await pending.StopSettled.Task.WaitAsync(TimeSpan.FromSeconds(12), token); }
        catch (TimeoutException) { lock (connectionMutex) connectionRecoveryRequired = true; throw; }
    }
    async Task AwaitConnectionReleaseAsync(MacConnectionPending pending)
    {
        try { await pending.ReleaseSettled.Task.WaitAsync(TimeSpan.FromSeconds(14)); }
        catch (TimeoutException) { lock (connectionMutex) connectionRecoveryRequired = true; throw; }
    }
    async Task PublishConnectionSettlementAsync(MacConnectionPending? pending, MacConnectionWorker worker)
    {
        if (pending is null) return;
        var fact = await worker.WorkerSettlement;
        pending.PublishSettlement(fact);
        if (fact.Cleanup != "complete") lock (connectionMutex) connectionRecoveryRequired = true;
    }
    static string ConnectionFailureMessage(string code) => code switch
    {
        "bootstrapFailed" => "本机读取助手未能完成连接。已保存记录保留，可重试。",
        "launchFailed" => "本机读取所需的微信副本启动后已退出，未开始读取。已保存记录保留，可重试。",
        "launchDeadline" => "本机读取所需的微信副本启动超时，未完成连接。已保存记录保留。",
        "ownerInvalid" => "本机账号身份未通过检查，未开始读取。已保存记录保留。",
        "managedBundleInvalid" or "signatureInvalid" => "本机读取所需的微信副本未通过完整性检查，未开始读取。已保存记录保留。",
        "existingApplication" => "本机读取所需的微信副本已经运行，未开始新的连接。已保存记录保留。",
        "identityChanged" => "本机读取所需的微信副本身份未能确认，已停止连接。已保存记录保留。",
        "stopDeadline" => "本机读取所需的微信副本未能确认结束，已停止连接。已保存记录保留。",
        _ => "本机连接未完成，已保存记录保留。"
    };
    void StartConnection(string selectedSource, string selected, string destination)
    {
        if (ConnectionImportBlocked) throw new ArgumentException(ConnectionRecoveryMessage);
        string canonical = Path.Combine(connectionHomeLookup(), "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files", selected);
        if (!string.Equals(selectedSource, canonical, StringComparison.Ordinal)) throw new ArgumentException("首次连接请选择本机微信账号目录；外部副本需先具备可用缓存凭据，未开始导入。");
        var previousStore = store; var previousOptions = Options; string selectedArchive = Path.Combine(directory, "archive");
        syncCancellation?.Dispose(); var cancellation = syncCancellation = OperationCancellation(TimeSpan.FromSeconds(380));
        var token = cancellation.Token; var worker = new MacConnectionWorker();
        lock (connectionMutex) { connectionWorker = worker; connectionCancellation = cancellation; }
        setupBusy = true; syncOutcome = "notice"; syncStatus = "正在准备本机连接…";
        syncWork = TrackShutdownTask(Task.Run(async () =>
        {
            bool successor = false, releaseWaitAttempted = false; MacConnectionPending? pending = null;
            try
            {
                string project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
                string binary = Path.GetFullPath(Path.Combine(project, "../worker/mac-worker"));
                var result = await worker.RunAsync(binary, selected, selectedArchive, item =>
                {
                    RuntimeEventSource.Emit(AppLogLevel.Information, "MAC_CONNECTION_WORKER_EVENT", "MacConnection", "本机读取助手状态已更新。",
                        new Dictionary<string, object?> { ["event"] = item.Event, ["state"] = item.State, ["code"] = item.Code,
                            ["cleanup"] = item.Cleanup, ["verified"] = item.Verified, ["missing"] = item.Missing });
                    if (item.Event == "authorize")
                    {
                        token.ThrowIfCancellationRequested(); pending = new MacConnectionPending(selected, item.Operation);
                        lock (connectionMutex) connectionPending = pending;
                        Post("chat", new { type = "macNative", command = "connectAccount", requestId = pending.RequestId });
                    }
                    string phase = item.Event == "authorize" ? "正在暂时退出微信并准备本机连接…" : item.State switch { "running" => "正在验证当前账号的本地读取凭据…", "cleaning" => "正在结束本机读取…", _ => "正在准备本机连接…" };
                    if (!token.IsCancellationRequested) Post("chat", new { type = "state", syncing = true, syncStatus = phase, syncDetail = $"已验证来源 {item.Verified}；待补来源 {item.Missing}。" });
                    return Task.CompletedTask;
                }, token);
                pending?.Finish();
                await PublishConnectionSettlementAsync(pending, worker);
                if (pending?.WasClaimed == true)
                {
                    await AwaitConnectionStopAsync(pending, CancellationToken.None);
                    releaseWaitAttempted = true; await AwaitConnectionReleaseAsync(pending);
                }
                token.ThrowIfCancellationRequested();
                if ((await worker.WorkerSettlement).Cleanup != "complete") { lock (connectionMutex) connectionRecoveryRequired = true; throw new ArgumentException(ConnectionRecoveryMessage); }
                if (!result.Usable) throw new ArgumentException(result.State == "repair_required" ? "已有凭据需要单独修复，已保留原有记录与缓存。" : "本机连接未完成，已保存记录保留，可重试。");
                await gate.WaitAsync(token);
                try
                {
                    token.ThrowIfCancellationRequested();
                    if (!ReferenceEquals(store, previousStore) || Options != previousOptions) throw new ArgumentException("记录位置已变化，请重新准备。");
                    var candidate = previousOptions with { AttachmentSourceDirectory = selectedSource, DatabasePath = destination, LocalChatSetupState = "pending" };
                    try
                    {
                        if (destination == store.DatabasePath) SaveOptions(candidate);
                        else
                        {
                            // This task itself owns syncWork; reuse the existing relocation transaction without recursively entering its busy guard.
                            if (exportBusy || DiagnosticsBusy || !voiceWork.IsCompleted || official?.Busy == true || File.Exists(destination)) throw new ArgumentException("目标位置已有记录库或其他处理尚未结束，请重新选择。");
                            knowledgeCancellation?.Cancel();
                            try { await knowledgeWork.WaitAsync(token); } catch (OperationCanceledException) when (!token.IsCancellationRequested) { }
                            var prepared = new SqliteMessageStore(destination, candidate.BackupRetentionCount);
                            await RecordStorageRelocator.RelocateAsync(store.DatabasePath, destination, _ => SaveOptions(candidate), null, token);
                            store = prepared;
                        }
                    }
                    catch { store = previousStore; savedOptions = previousOptions; throw; }
                    setupFolderRequests.Clear(); setupStartupChecked = true;
                    StartSetupImport(selectedSource, selected); successor = true;
                }
                finally { gate.Release(); }
            }
            catch (Exception error) when (error is not OutOfMemoryException)
            {
                pending?.Revoke(); worker.Revoke();
                await PublishConnectionSettlementAsync(pending, worker); // Independent of cancelled operation token, before Native waits.
                if (pending?.WasClaimed == true && !pending.StopSettled.Task.IsCompleted)
                    try { await AwaitConnectionStopAsync(pending, CancellationToken.None); }
                    catch (TimeoutException) { }
                if (pending?.WasClaimed == true && pending.StopSettled.Task.IsCompleted && !releaseWaitAttempted && !pending.ReleaseSettled.Task.IsCompleted)
                    try { releaseWaitAttempted = true; await AwaitConnectionReleaseAsync(pending); } catch (TimeoutException) { }
                await gate.WaitAsync();
                try
                {
                    setupOpen = true; setupBusy = false;
                    bool recovery; lock (connectionMutex) recovery = connectionRecoveryRequired;
                    setupError = recovery ? ConnectionRecoveryMessage : pending?.FailureCode is { } code ? ConnectionFailureMessage(code) : error is OperationCanceledException ? "本机连接已取消，已保存记录保留，可重试。" : error is ArgumentException ? error.Message : "本机连接未完成，已保存记录保留，可重试。";
                    syncOutcome = !recovery && pending?.FailureCode is null && error is OperationCanceledException ? "cancelled" : "failed"; syncStatus = setupError;
                }
                finally { gate.Release(); }
            }
            finally
            {
                pending?.Revoke(); worker.Revoke();
                lock (connectionMutex)
                {
                    if (pending?.WasClaimed == true) connectionTombstone = pending;
                    // Retain an uncancellable Native operation until its final release; late auth/quit callbacks still own it.
                    if (pending?.WasClaimed != true || pending.ReleaseSettled.Task.IsCompleted)
                    { connectionPending = null; connectionWorker = null; connectionCancellation = null; }
                }
                if (!successor)
                {
                    await gate.WaitAsync();
                    try { Post("chat", new { type = "state", setup = SetupState(), syncing = false, syncOutcome, syncStatus }); }
                    finally { gate.Release(); }
                }
            }
        }));
    }
}

internal static class MacConnectionOwner
{
    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    struct PasswordEntry
    {
        public IntPtr Name, Password;
        public uint UID, GID;
        public long Change;
        public IntPtr Class, Gecos, Directory, Shell;
        public long Expire;
        public int Fields;
    }
    [System.Runtime.InteropServices.DllImport("/usr/lib/libSystem.B.dylib")] static extern uint getuid();
    [System.Runtime.InteropServices.DllImport("/usr/lib/libSystem.B.dylib")] static extern uint geteuid();
    [System.Runtime.InteropServices.DllImport("/usr/lib/libSystem.B.dylib")] static extern int getpwuid_r(uint uid, out PasswordEntry entry, IntPtr buffer, nuint count, out IntPtr found);
    internal static string Home()
    {
        uint uid = getuid(); if (uid == 0 || uid != geteuid()) throw new ArgumentException("本机账号身份不可用。");
        IntPtr buffer = System.Runtime.InteropServices.Marshal.AllocHGlobal(65536);
        try
        {
            if (getpwuid_r(uid, out var entry, buffer, 65536, out var found) != 0 || found == IntPtr.Zero || entry.UID != uid || entry.Directory == IntPtr.Zero) throw new ArgumentException("本机账号身份不可用。");
            string? home = System.Runtime.InteropServices.Marshal.PtrToStringUTF8(entry.Directory);
            if (home is null || !Path.IsPathFullyQualified(home) || home == "/" || Path.GetFullPath(home) != home || home.Any(c => char.IsControl(c))) throw new ArgumentException("本机账号身份不可用。");
            return home;
        }
        finally { System.Runtime.InteropServices.Marshal.FreeHGlobal(buffer); }
    }
}
