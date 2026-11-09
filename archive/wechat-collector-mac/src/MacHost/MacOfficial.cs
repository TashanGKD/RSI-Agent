using System.Text.Json;
using System.Collections.Concurrent;
using WechatUiCollector.Desktop;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    OfficialAccountsController? official;
    OfficialAccountsWeb? officialWeb;
    readonly ConcurrentQueue<JsonElement> officialCommands = new();
    Task officialDispatch = Task.CompletedTask;
    async Task OfficialAsync(JsonElement command, CancellationToken token)
    {
        if (official is null)
        {
            official = new(() => store, () => store.DatabasePath, LifetimeToken);
            officialWeb = new(official,
                text => Post("official", new { type = "macNative", command = "clipboard", text }),
                url => { if (Uri.TryCreate(url, UriKind.Absolute, out var link) && link.Scheme is "https" or "http") Post("official", new { type = "macNative", command = "openUrl", url }); },
                LifetimeToken);
            officialWeb.Page.Outgoing += value => Post("official", value);
            official.ErrorReported += (title, text) => Post("official", new { type = "macNative", command = "notice", text = title + "\n" + text });
        }
        if (Text(command, "action") == "ready") { await official.RefreshDirectoryAsync(); await officialWeb!.Page.DispatchAsync(command); return; }
        if (Text(command, "action").StartsWith("cancel", StringComparison.Ordinal)) { await officialWeb!.Page.DispatchAsync(command); return; }
        officialCommands.Enqueue(command.Clone());
        // Always schedule a successor: the prior pump may have seen an empty queue
        // before its task completes. HandleAsync serializes this chain assignment.
        officialDispatch = TrackShutdownTask(officialDispatch.ContinueWith(async previous =>
        {
            _ = previous.Exception; // A failed predecessor must not strand later commands.
            while (!LifetimeToken.IsCancellationRequested && officialCommands.TryDequeue(out var next))
                try { await officialWeb!.Page.DispatchAsync(next); }
                catch (Exception error) when (error is not OutOfMemoryException) { Post("official", new { type = "macNative", command = "notice", text = error is ArgumentException ? error.Message : "这项操作未完成，请检查后重试。" }); }
        }, CancellationToken.None, TaskContinuationOptions.None, TaskScheduler.Default).Unwrap());
    }
}
