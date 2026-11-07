using WechatUiCollector.Configuration;
using WechatUiCollector.Diagnostics;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;
public sealed partial class MacController
{
    string SafeUserOutput(string path) => MacOutputProtection.Resolve(path,store.DatabasePath,directory,archive,
        [ConfigurationLoader.ResolvePath(Options.LogDirectory,directory),ConfigurationLoader.ResolvePath(Options.MediaDirectory,directory),ConfigurationLoader.ResolvePath(Options.JsonlOutputPath,directory),ConfigurationLoader.ResolvePath(Options.AvatarCatalogPath,directory),Path.Combine(directory,"bridge-token"),Path.Combine(directory,"bridge-entry.json"),Path.Combine(directory,"entry"),Path.Combine(directory,"bridge-errors.log"),Path.Combine(directory,"profile-ext-credentials.v1.json")]);
    static void CleanupUserTemporary(string? path)
    {
        try { if(path is not null&&File.Exists(path))ProtectedFileSystem.Delete(path); }
        catch(Exception error)when(error is IOException or UnauthorizedAccessException)
        { RuntimeEventSource.Emit(AppLogLevel.Warning,"MAC_EXPORT_TEMP_CLEANUP_FAILED","MacExport","临时导出文件未清理。",new Dictionary<string,object?>{["errorType"]=error.GetType().Name}); }
    }
}
