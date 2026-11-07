using System.Text.RegularExpressions;
using WechatUiCollector.Storage;

namespace WechatCollector.Mac;

public sealed partial class MacController
{
    sealed record AvatarBinding(string Database, string Account, string Hash);
    readonly object avatarLock = new();
    readonly Dictionary<AvatarBinding, string> avatarIdentifiers = new();
    readonly Dictionary<string, AvatarBinding> avatarBindings = new(StringComparer.Ordinal);
    readonly Queue<string> avatarOrder = new();
    readonly SemaphoreSlim avatarReads = new(3);

    string? AvatarUrl(string selectedAccount, string? hash)
    {
        if (string.IsNullOrEmpty(selectedAccount) || hash is null || !Regex.IsMatch(hash, @"\A[0-9A-Fa-f]{64}\z")) return null;
        var binding = new AvatarBinding(store.DatabasePath, selectedAccount, hash.ToUpperInvariant());
        lock (avatarLock)
        {
            if (!avatarIdentifiers.TryGetValue(binding, out var id))
            {
                id = Guid.NewGuid().ToString("N");
                avatarIdentifiers.Add(binding, id); avatarBindings.Add(id, binding); avatarOrder.Enqueue(id);
                while (avatarBindings.Count > 16384 && avatarOrder.TryDequeue(out var oldest))
                    if (avatarBindings.Remove(oldest, out var expired)) avatarIdentifiers.Remove(expired);
            }
            return "/avatar/" + id;
        }
    }

    public async Task<StoredAvatar?> ReadAvatarResourceAsync(string id, CancellationToken token)
    {
        if (!Regex.IsMatch(id, @"\A[0-9a-f]{32}\z")) return null;
        AvatarBinding? binding;
        lock (avatarLock) avatarBindings.TryGetValue(id, out binding);
        var source = store;
        if (binding is null || binding.Database != source.DatabasePath) return null;
        using var operation = CancellationTokenSource.CreateLinkedTokenSource(token, LifetimeToken);
        operation.CancelAfter(TimeSpan.FromSeconds(10));
        await avatarReads.WaitAsync(operation.Token);
        try
        {
            var image = await source.ReadAvatarAsync(binding.Account, binding.Hash, operation.Token);
            if (binding.Database != store.DatabasePath || image is null || image.Bytes.Length is < 1 or > 1048576 ||
                image.ContentType is not ("image/png" or "image/jpeg" or "image/gif" or "image/webp")) return null;
            return image;
        }
        finally { avatarReads.Release(); }
    }
}
