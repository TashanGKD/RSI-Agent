using System.Collections.Concurrent;
using System.Diagnostics;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    readonly CancellationTokenSource lifetimeCancellation = new();
    readonly ConcurrentDictionary<Task, byte> shutdownTasks = new();
    int stopRequested;
    readonly TaskCompletionSource stopCallbacksFinished = new(TaskCreationOptions.RunContinuationsAsynchronously);
    Task shutdownCleanup = Task.CompletedTask;
    Task exportWork = Task.CompletedTask;
    Task personaWork = Task.CompletedTask;
    public CancellationToken LifetimeToken => lifetimeCancellation.Token;

    CancellationTokenSource OperationCancellation(TimeSpan? timeout = null)
    {
        var source = CancellationTokenSource.CreateLinkedTokenSource(LifetimeToken);
        if (timeout is { } duration) source.CancelAfter(duration);
        return source;
    }

    Task TrackShutdownTask(Task task)
    {
        shutdownTasks.TryAdd(task, 0);
        _ = task.ContinueWith(completed =>
        {
            _ = completed.Exception; // Observe background failures, including after a bounded wait expires.
            shutdownTasks.TryRemove(completed, out _);
        }, CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        return task;
    }

    static void SafeShutdown(Action action)
    {
        try { action(); }
        catch (Exception error) when (error is not OutOfMemoryException) { }
    }
    static void CancelForShutdown(CancellationTokenSource? source)
    {
        if (source is not null) SafeShutdown(source.Cancel);
    }

    // Cancellation only reaches owned operation tokens and the owned worker
    // pool. Never discover or kill a process by application name or PID scan.
    public void RequestStop()
    {
        if (Interlocked.Exchange(ref stopRequested, 1) != 0) return;
        try
        {
        CancelForShutdown(lifetimeCancellation);
        foreach (var source in new[] { syncCancellation, voiceCancellation, autoCancellation, knowledgeCancellation, exportCancellation, personaCancellation, diagnosticsCancellation, liveLogsCancellation, forwardedCancellation, forwardedFileCancellation })
            CancelForShutdown(source);
        foreach (var source in thumbnailJobs.Values) CancelForShutdown(source);
        autoPaused = true; logsVisible = false;
        lock (voiceQueue) voiceQueue.Clear();
        officialCommands.Clear();
        SafeShutdown(() => Interlocked.Exchange(ref personaWatcher, null)?.Dispose());
        SafeShutdown(() => Interlocked.Exchange(ref playbackLease, null)?.Dispose());
        SafeShutdown(mediaWorkers.Dispose);
        SafeShutdown(foregroundMediaWorkers.Dispose);
        SafeShutdown(StopDiagnostics);
        if (official is { } activeOfficial) SafeShutdown(activeOfficial.CancelAllFlows);
        if (officialWeb is { } web) SafeShutdown(() => TrackShutdownTask(web.CloseAsync()));
        shutdownCleanup = ClearStoppedStateAsync();
        }
        finally { stopCallbacksFinished.TrySetResult(); }
    }

    async Task ClearStoppedStateAsync()
    {
        // A command already inside the gate may be unwinding. Do not block the
        // synchronous stopping callback, and do not clear mutable maps under it.
        await gate.WaitAsync();
        try
        {
            SafeShutdown(() => Interlocked.Exchange(ref personaWatcher, null)?.Dispose());
            SafeShutdown(() => Interlocked.Exchange(ref playbackLease, null)?.Dispose());
            pendingExports.Clear(); pendingTimelines.Clear(); pendingDocuments.Clear(); diagnosticExports.Clear();
            mediaResources.Clear(); stickerResources.Clear(); searchMatches.Clear(); knowledgeMatches.Clear();
            forwardedSession = null; forwardedFiles = null; forwardedFilesSession = null;
            trustedSingleImageLoader = null; imageMessages = [];
            foreach (var queue in events.Values) lock (queue) queue.Clear();
            events.Clear(); chatStateFields.Clear(); overflowReported.Clear();
        }
        finally { gate.Release(); }
    }

    static async Task ObserveShutdownTask(Task task)
    {
        try { await task.ConfigureAwait(false); }
        catch (Exception error) when (error is not OutOfMemoryException) { }
    }

    /// <returns>True when known work drained; false when the finite grace period expired.</returns>
    public async Task<bool> WaitForStopAsync(TimeSpan? timeout = null)
    {
        var grace = timeout ?? TimeSpan.FromSeconds(3);
        if (grace < TimeSpan.Zero || grace > TimeSpan.FromSeconds(30)) throw new ArgumentOutOfRangeException(nameof(timeout));
        RequestStop();
        var elapsed = Stopwatch.StartNew();
        while (true)
        {
            var tasks = new List<Task> { syncWork, voiceWork, knowledgeWork, exportWork, personaWork, officialDispatch, diagnosticsWork, shutdownCleanup, stopCallbacksFinished.Task };
            tasks.AddRange(shutdownTasks.Keys);
            bool officialSnapshotStable = true;
            if (official is { } activeOfficial)
                try { tasks.AddRange(activeOfficial.ReadTasks.ToArray()); tasks.AddRange(activeOfficial.FlowTasks.ToArray()); }
                catch (Exception error) when (error is InvalidOperationException or ArgumentException) { officialSnapshotStable = false; }
            var pending = tasks.Where(task => task is not null && !task.IsCompleted).Distinct().ToArray();
            // Observe already completed faults as well as waiting work.
            foreach (var task in tasks.Where(task => task is { IsFaulted: true })) _ = task.Exception;
            if (pending.Length == 0 && officialSnapshotStable) return true;
            var remaining = grace - elapsed.Elapsed;
            if (remaining <= TimeSpan.Zero) return false;
            try
            {
                var drain = pending.Length == 0 ? Task.Delay(TimeSpan.FromMilliseconds(10)) : Task.WhenAll(pending.Select(ObserveShutdownTask));
                await drain.WaitAsync(remaining).ConfigureAwait(false);
            }
            catch (TimeoutException) { return false; }
        }
    }
}
