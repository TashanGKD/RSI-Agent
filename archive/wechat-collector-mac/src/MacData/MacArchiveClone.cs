using System.Runtime.InteropServices;
using Microsoft.Data.Sqlite;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;
public static class MacArchiveClone
{
    // Production always chooses the accepted fixed path/lease preparation. This
    // internal pair lets synthetic consumers avoid the production coordinator.
    internal sealed record Preparation(
        Func<string,string,CancellationToken,Task<MacArchiveLease.ClonePaths>> Paths,
        Func<IReadOnlyList<ArchiveLeaseRequest>,CancellationToken,Task<MacArchiveLease>> Lease);
    static readonly Preparation Production=new(MacArchiveLease.PrepareClonePathsAsync,MacArchiveLease.AcquireAsync);
    public static Task<string> PrepareAsync(string source,string state,CancellationToken token) =>
        PrepareAsync(source,state,token,Production);

    internal static async Task<string> PrepareAsync(string source,string state,CancellationToken token,Preparation preparation)
    {
        string result=Path.Combine(state,"archive");
        using var paths=await preparation.Paths(source,state,token);
        var requests=new List<ArchiveLeaseRequest>();
        if(paths.SourceExists)requests.Add(new(paths.SourcePath,ArchiveLeaseMode.Shared));
        requests.Add(new(paths.DestinationPath,ArchiveLeaseMode.Exclusive));
        // This scope owns actual flock descriptors through all copy and SQLite
        // disposal. The provider can launch its refresh only after this returns.
        await using var authority=await preparation.Lease(requests,token);
        paths.AdoptDestinationAfterWaiting(authority);
        void Check(){token.ThrowIfCancellationRequested();paths.CheckCurrent();authority.CheckCurrent();}
        Check();
        if(paths.DestinationIndexExists())return result;
        if(paths.PhysicalRelation!=MacArchiveLease.ClonePathRelation.Disjoint)
            throw new IOException("来源与保存归档不能相同或互相嵌套。");
        source=paths.SourcePath;string destination=paths.DestinationPath;
        SourcePathProtection.ProtectDirectory(source);
        await MacArchiveClonePreflight.ValidateAsync(source,destination,token);
        Check();paths.CreateDestination(authority,token);Check();
        foreach(var name in new[]{"accounts","keys"})
        {
            Check();var root=Path.Combine(source,name);if(!Directory.Exists(root))continue;
            foreach(var file in Directory.EnumerateFiles(root,"*",new EnumerationOptions { RecurseSubdirectories=true,AttributesToSkip=FileAttributes.ReparsePoint }))
            {
                Check();string target=SourcePathProtection.WritablePath(Path.Combine(destination,name,Path.GetRelativePath(root,file)));
                ProtectedFileSystem.CreateDirectory(Path.GetDirectoryName(target)!);
                if(!File.Exists(target))
                {
                    Check();
                    if(!OperatingSystem.IsMacOS() || CloneFile(file,target,0)!=0)ProtectedFileSystem.Copy(file,target);
                    File.SetUnixFileMode(target,UnixFileMode.UserRead|UnixFileMode.UserWrite);
                    Check();
                }
            }
        }
        Check();
        if(paths.SourceFileExists("capture-consent.json"))
        {
            ProtectedFileSystem.Copy(Path.Combine(source,"capture-consent.json"),Path.Combine(destination,"capture-consent.json"),overwrite:true);
            File.SetUnixFileMode(Path.Combine(destination,"capture-consent.json"),UnixFileMode.UserRead|UnixFileMode.UserWrite);Check();
        }
        if(paths.SourceFileExists("index.db"))
        {
            using var input=await paths.PrepareSqliteInputAsync(authority,token);
            // SQLite can create/recover WAL and SHM even for a readonly source.
            // It opens only this owned private copy, never the source path.
            await using(var original=new SqliteConnection(new SqliteConnectionStringBuilder { DataSource=input.InputPath,Mode=SqliteOpenMode.ReadWrite,Pooling=false }.ToString()))
            await using(var copy=new SqliteConnection(new SqliteConnectionStringBuilder { DataSource=input.ResultPath,Mode=SqliteOpenMode.ReadWrite,Pooling=false }.ToString()))
            {
                input.Check();await original.OpenAsync(token);input.Check();await copy.OpenAsync(token);input.Check();original.BackupDatabase(copy);input.Check();
                using var check=copy.CreateCommand();check.CommandText="PRAGMA integrity_check";
                if(await check.ExecuteScalarAsync(token) as string!="ok")throw new IOException("读取副本校验未通过，原归档保留。");
            }
            Check();input.Check();input.Publish();Check();
        }
        Check();return result;
    }
    internal static void CopySnapshot(string source, string destination)
    {
        SourcePathProtection.WritablePath(destination);
        if (!OperatingSystem.IsMacOS() || CloneFile(source, destination, 0) != 0) ProtectedFileSystem.Copy(source, destination);
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(destination, UnixFileMode.UserRead | UnixFileMode.UserWrite);
    }
    [DllImport("libSystem.B.dylib", EntryPoint = "clonefile", SetLastError = true)]
    static extern int CloneFile([MarshalAs(UnmanagedType.LPUTF8Str)] string source, [MarshalAs(UnmanagedType.LPUTF8Str)] string destination, int flags);
}
