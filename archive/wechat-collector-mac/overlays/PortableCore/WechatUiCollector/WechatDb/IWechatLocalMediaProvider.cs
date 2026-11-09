using System;
using System.Threading;
using System.Threading.Tasks;
using WechatUiCollector.Collection;

namespace WechatUiCollector.WechatDb;

// Mac implementation is supplied by the same startup-owned local import provider.
// Methods read verified local media; none may capture keys or request permissions.
public interface IWechatLocalMediaProvider
{
    string ValidateMediaAccountRoot(string root, string account);
    string ProtectMediaOutput(string destination, string database);
    Task<WechatImagePreviewResult> LoadMessageImageAsync(string root, WechatDbMessage message, CancellationToken token);
    Task<byte[]> LoadMessageVoiceAsync(string root, WechatDbMessage message, CancellationToken token);
    Task<WechatImagePreviewResult> DecodeAccountImageAsync(string file, string? template, CancellationToken token);
}
