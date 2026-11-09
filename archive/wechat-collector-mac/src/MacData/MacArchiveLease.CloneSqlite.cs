using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using WechatUiCollector.Safety;

namespace WechatCollector.Mac;

public sealed partial class MacArchiveLease
{
    internal sealed partial class ClonePaths
    {
        internal async Task<CloneSqliteInput> PrepareSqliteInputAsync(MacArchiveLease authority,CancellationToken token)
        {
            AdoptDestinationAfterWaiting(authority);token.ThrowIfCancellationRequested();
            var input=new CloneSqliteInput(this,authority);
            try { await input.CopyAsync(token);return input; }
            catch { input.Dispose();throw; }
        }
        // Only SQLite input/backup is staged. Accounts keep the separately
        // accepted bounded generation preflight; this is not archive staging.
        internal sealed class CloneSqliteInput : IDisposable
        {
            static readonly string[] Suffixes=["","-wal","-shm","-journal"];
            readonly ClonePaths owner;readonly MacArchiveLease authority;
            readonly string name;readonly Native.Stat directoryPin;
            readonly Native.Stat?[] sourcePins;
            readonly Dictionary<string,(int Fd,Native.Stat Pin)> files=new(StringComparer.Ordinal);
            int fd=-1;bool disposed;
            internal string DirectoryPath { get; }
            internal string InputPath=>Path.Combine(DirectoryPath,"input.db");
            internal string ResultPath=>Path.Combine(DirectoryPath,"result.db");
            internal CloneSqliteInput(ClonePaths owner,MacArchiveLease authority)
            {
                this.owner=owner;this.authority=authority;
                name=".clone-index-"+Guid.NewGuid().ToString("N");DirectoryPath=Path.Combine(owner.DestinationPath,name);
                SourcePathProtection.WritablePath(DirectoryPath);sourcePins=new Native.Stat?[Suffixes.Length];
                owner.CheckCurrent();authority.CheckCurrent();
                for(int i=0;i<Suffixes.Length;i++)if(Native.TryStatAt(owner.source.Chain.Fd,"index.db"+Suffixes[i],out var pin))
                {
                    if((pin.Mode&0xf000)!=0x8000 || pin.Uid!=owner.uid)throw Invalid();sourcePins[i]=pin;
                }
                if(sourcePins[0] is null)throw Invalid();
                if(Native.MkdirAt(owner.destination.Chain.Fd,name,0x1c0)!=0)throw Invalid();
                fd=Native.OpenAt(owner.destination.Chain.Fd,name,Native.DirectoryFlags);if(fd<0)throw Invalid();
                try
                {
                    directoryPin=Native.Private(fd,owner.uid,true);Match(directoryPin,Native.StatAt(owner.destination.Chain.Fd,name));Check();
                    // Reserve every SQLite filename. Cleanup never adopts an
                    // unrecorded or replaced inode in the private stage.
                    foreach(string prefix in new[]{"input.db","result.db"})foreach(string suffix in Suffixes)
                    {
                        string leaf=prefix+suffix;
                        // Managed CreateNew supplies the platform's variadic-open
                        // ABI; retain a separate nofollow native FD, not its share lock.
                        using(var created=new FileStream(Path.Combine(DirectoryPath,leaf),new FileStreamOptions { Mode=FileMode.CreateNew,Access=FileAccess.ReadWrite,Share=FileShare.ReadWrite|FileShare.Delete,UnixCreateMode=(UnixFileMode)0x180,BufferSize=1 }))
                        {
                            var pin=Native.Private((int)created.SafeFileHandle.DangerousGetHandle(),owner.uid,false);
                            int opened=Native.OpenAt(fd,leaf,Native.FileFlags);if(opened<0)throw Invalid();
                            try{Match(pin,Native.Private(opened,owner.uid,false));Match(pin,Native.StatAt(fd,leaf));files.Add(leaf,(opened,pin));opened=-1;}
                            finally{if(opened>=0)Native.Close(opened);}
                        }
                    }
                    Check();
                }
                catch{Dispose();throw;}
            }
            internal async Task CopyAsync(CancellationToken token)
            {
                byte[] buffer=new byte[64*1024];
                for(int i=0;i<Suffixes.Length;i++)
                {
                    token.ThrowIfCancellationRequested();Check();if(sourcePins[i] is not {} before)continue;
                    string sourceName="index.db"+Suffixes[i];int original=Native.OpenAt(owner.source.Chain.Fd,sourceName,0x1000000|0x100|4);
                    if(original<0)throw Invalid();
                    try
                    {
                        Native.CheckFlags(original,false);InputMatch(before,Native.FStat(original));
                        using var readHandle=new SafeFileHandle((IntPtr)original,ownsHandle:false);
                        using var writeHandle=new SafeFileHandle((IntPtr)files["input.db"+Suffixes[i]].Fd,ownsHandle:false);
                        using var source=new FileStream(readHandle,FileAccess.Read,buffer.Length,isAsync:false);
                        using var target=new FileStream(writeHandle,FileAccess.Write,buffer.Length,isAsync:false);
                        for(;;)
                        {
                            token.ThrowIfCancellationRequested();Check();int count=await source.ReadAsync(buffer,token);if(count==0)break;
                            await target.WriteAsync(buffer.AsMemory(0,count),token);
                        }
                        await target.FlushAsync(token);InputMatch(before,Native.FStat(original));Check();
                    }
                    finally{Native.Close(original);}
                }
                token.ThrowIfCancellationRequested();Check();
            }
            static void InputMatch(Native.Stat before,Native.Stat after)
            {
                Match(before,after);
                if(before.Size!=after.Size || before.NLink!=after.NLink || before.MTime!=after.MTime || before.MTimeNs!=after.MTimeNs || before.CTime!=after.CTime || before.CTimeNs!=after.CTimeNs)throw Invalid();
            }
            internal void Check()
            {
                if(disposed || fd<0)throw Invalid();owner.CheckCurrent();authority.CheckCurrent();
                Match(directoryPin,Native.Private(fd,owner.uid,true));Match(directoryPin,Native.StatAt(owner.destination.Chain.Fd,name));
                for(int i=0;i<Suffixes.Length;i++)
                {
                    bool exists=Native.TryStatAt(owner.source.Chain.Fd,"index.db"+Suffixes[i],out var current);
                    if(sourcePins[i] is {} before){if(!exists)throw Invalid();InputMatch(before,current);}else if(exists)throw Invalid();
                }
                foreach(var file in files)
                {
                    if(Native.TryStatAt(fd,file.Key,out var current)){Match(file.Value.Pin,Native.PrivateContentFile(file.Value.Fd,owner.uid));Match(file.Value.Pin,current);}
                    else if(file.Key is "input.db" or "result.db")throw Invalid();
                }
            }
            internal void Publish()
            {
                Check();string destination=Path.Combine(owner.DestinationPath,"index.db");
                if(Native.TryStatAt(owner.destination.Chain.Fd,"index.db",out _))throw Invalid();
                // SQLite handles are closed. The result inode was created600.
                ProtectedFileSystem.Move(ResultPath,destination);owner.CheckCurrent();authority.CheckCurrent();
            }
            public void Dispose()
            {
                if(disposed)return;
                try
                {
                    if(fd>=0)
                    {
                        owner.CheckCurrent();authority.CheckCurrent();
                        Match(directoryPin,Native.Private(fd,owner.uid,true));Match(directoryPin,Native.StatAt(owner.destination.Chain.Fd,name));
                        var present=Directory.EnumerateFileSystemEntries(DirectoryPath).Select(Path.GetFileName).ToArray();
                        foreach(string? leaf in present)
                        {
                            if(leaf is null || !files.TryGetValue(leaf,out var file))throw Invalid();
                            Match(file.Pin,Native.PrivateContentFile(file.Fd,owner.uid));Match(file.Pin,Native.StatAt(fd,leaf));
                        }
                        foreach(string? leaf in present)if(Native.UnlinkAt(fd,leaf!,0)!=0)throw Invalid();
                        Match(directoryPin,Native.StatAt(owner.destination.Chain.Fd,name));_ = Native.UnlinkAt(owner.destination.Chain.Fd,name,0x80);
                    }
                }
                catch(Exception error) when(error is IOException or UnauthorizedAccessException) { /* Preserve every uncertain/substituted entry. */ }
                finally{disposed=true;foreach(var file in files.Values)Native.Close(file.Fd);files.Clear();if(fd>=0){Native.Close(fd);fd=-1;}}
            }
        }
    }
    static partial class Native
    {
        // Content files share A's owner/mode/noACL policy, while lock nodes
        // retain their original mandatory zero-length policy unchanged.
        internal static Stat PrivateContentFile(int fd,uint uid)
        {
            var value=FStat(fd);CheckFlags(fd,true);
            if(value.Uid!=uid || (value.Mode&0xfff)!=0x180 || (value.Mode&0xf000)!=0x8000 || value.NLink!=1)throw Invalid();
            IntPtr acl=GetAcl(fd,256);
            if(acl==IntPtr.Zero){if(Marshal.GetLastPInvokeError()!=2)throw Invalid();}
            else{try{if(GetAclEntry(acl,0,out _)==0 || Marshal.GetLastPInvokeError()!=22)throw Invalid();}finally{FreeAcl(acl);}}
            return value;
        }
        [DllImport(Lib,EntryPoint="unlinkat",SetLastError=true)]internal static extern int UnlinkAt(int parent,[MarshalAs(UnmanagedType.LPUTF8Str)]string name,int flags);
    }
}
