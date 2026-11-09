using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace WechatCollector.Mac;

public enum ArchiveLeaseMode { Shared, Exclusive }
public sealed record ArchiveLeaseRequest(string Path, ArchiveLeaseMode Mode);

// Preparation never confers ownership. This process owns every flock fd from
// successful acquisition until Dispose, which the caller performs after its I/O.
public sealed partial class MacArchiveLease : IDisposable, IAsyncDisposable
{
    const string Failure = "归档协调校验失败。";
    readonly object gate = new();
    readonly uint uid;
    readonly int pid;
    readonly List<Target> targets = [];
    readonly List<LockNode> locks = [];
    Chain? coordination;
    int privateDirectoryCount;
    bool disposed;
    MacArchiveLease(uint uid) { this.uid = uid; pid = Native.GetPid(); }

    public static Task<MacArchiveLease> AcquireAsync(IReadOnlyList<ArchiveLeaseRequest> requests, CancellationToken token)
    {
        uint uid = Native.OrdinaryUid();
        string home = Canonical(Native.UserHome(uid));
        string root = Path.Combine(home, "Library/Application Support/WechatCollectorMac/archive-locks/parent-leaf-v1");
        return AcquireCoreAsync(requests, root, 3, home, PrepareAsync, token);
    }
    // Fixture-only injection. Neither the worker protocol nor environment has
    // helper/home/root overrides. The harness compiles this source in its assembly.
    internal static Task<MacArchiveLease> AcquireForTestsAsync(IReadOnlyList<ArchiveLeaseRequest> requests, string root,
        Func<string, CancellationToken, Task<string>> prepare, CancellationToken token) =>
        AcquireCoreAsync(requests, Canonical(root), 1, Canonical(Native.UserHome(Native.OrdinaryUid())), prepare, token);

    static async Task<MacArchiveLease> AcquireCoreAsync(IReadOnlyList<ArchiveLeaseRequest> requests, string root,
        int privateCount, string home, Func<string, CancellationToken, Task<string>> prepare, CancellationToken token)
    {
        if (!OperatingSystem.IsMacOS()) throw new PlatformNotSupportedException();
        uint uid = Native.OrdinaryUid();
        var lease = new MacArchiveLease(uid) { privateDirectoryCount = privateCount };
        try
        {
            token.ThrowIfCancellationRequested();
            if (requests is null || requests.Count is < 1 or > 2) throw Invalid();
            // Validate all roles and hold parent chains before invoking a process
            // that can create any permanent coordination entry.
            foreach (var request in requests)
            {
                if (request is null || request.Mode is not (ArchiveLeaseMode.Shared or ArchiveLeaseMode.Exclusive)) throw Invalid();
                var target = new Target(request, uid); lease.targets.Add(target);
                if (target.Path == "/" || target.Path == home || Overlap(target.Path, root)) throw Invalid();
                var homePin = Native.LStat(home);
                if (target.Existing is { } existing && SameIdentity(existing, homePin)) throw Invalid();
                // Physical ancestry catches firmlink aliases of the reserved tree.
                using var anchor = new Chain(root, missingOk:true);
                if (target.Existing is { } x && anchor.Pins.Any(p => SameIdentity(x, p))) throw Invalid();
                if (anchor.Complete && target.ContainsParent(Native.FStat(anchor.Fd))) throw Invalid();
                if (!anchor.Complete && target.Existing is null && SameIdentity(target.Parent,Native.FStat(anchor.Fd)) &&
                    string.Equals(Path.GetFileName(target.Path),anchor.MissingName,StringComparison.OrdinalIgnoreCase)) throw Invalid();
            }
            string nonce = Guid.NewGuid().ToString("N");
            string requestJson = JsonSerializer.Serialize(new { v = 1, request = nonce, targets = lease.targets.Select(t => new { path = t.Path, mode = ModeText(t.Mode) }) });
            if (Encoding.UTF8.GetByteCount(requestJson) + 1 > 8192) throw Invalid();
            foreach (var target in lease.targets) target.Check();
            string raw = await prepare(requestJson, token);
            token.ThrowIfCancellationRequested();
            var bindings = ParsePrepared(raw, nonce, lease.targets);
            lease.coordination = new Chain(root);
            lease.CheckDirectories();
            var modes = new SortedDictionary<string, ArchiveLeaseMode>(StringComparer.Ordinal);
            for (int i = 0; i < bindings.Length; i++)
            {
                string id = bindings[i]; var mode = lease.targets[i].Mode;
                if (!modes.TryGetValue(id, out var prior) || mode == ArchiveLeaseMode.Exclusive) modes[id] = mode;
            }
            foreach (var pair in modes)
            {
                token.ThrowIfCancellationRequested();
                int fd = Native.OpenAt(lease.coordination.Fd, pair.Key, Native.FileFlags);
                if (fd < 0) throw Invalid();
                var node = new LockNode(fd, pair.Key); lease.locks.Add(node);
                node.Pin = Native.Private(fd, uid, false);
                Match(node.Pin, Native.StatAt(lease.coordination.Fd, pair.Key));
                for (;;)
                {
                    token.ThrowIfCancellationRequested();
                    if (Native.Flock(fd, (pair.Value == ArchiveLeaseMode.Exclusive ? 2 : 1) | 4) == 0) break;
                    int error = Marshal.GetLastPInvokeError();
                    if (error != 35) throw Invalid(); // Darwin EWOULDBLOCK only.
                    await Task.Delay(25, token);
                }
            }
            lease.CheckCurrent(); token.ThrowIfCancellationRequested(); return lease;
        }
        catch { lease.Dispose(); throw; }
    }
    static bool Overlap(string path, string root) => path == root || path.StartsWith(root + "/", StringComparison.Ordinal) || root.StartsWith(path + "/", StringComparison.Ordinal);
    static string ModeText(ArchiveLeaseMode mode) => mode == ArchiveLeaseMode.Shared ? "shared" : "exclusive";
    static IOException Invalid() => new(Failure);
    static bool SameIdentity(Native.Stat a, Native.Stat b) => a.Dev == b.Dev && a.Ino == b.Ino;
    static void Match(Native.Stat a, Native.Stat b)
    {
        if (!SameIdentity(a,b) || a.Uid != b.Uid || a.Gid != b.Gid || a.Mode != b.Mode) throw Invalid();
    }
    static string[] ParsePrepared(string raw, string nonce, List<Target> targets)
    {
        try
        {
            if (Encoding.UTF8.GetByteCount(raw) is < 1 or > 8192 || raw.Contains('\0') || !raw.EndsWith('\n') || raw.Count(c => c == '\n') != 1) throw Invalid();
            using var doc = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 4 });
            var value = doc.RootElement;
            Exact(value, ["v", "status", "request", "bindings"]);
            if (!value.GetProperty("v").TryGetInt32(out int version) || version != 1 || Text(value,"status") != "prepared" || Text(value,"request") != nonce) throw Invalid();
            var array = value.GetProperty("bindings");
            if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() != targets.Count) throw Invalid();
            string[] result = new string[targets.Count]; int i=0;
            foreach (var item in array.EnumerateArray())
            {
                Exact(item,["id","mode","parentDev","parentIno"]);
                string id = Text(item,"id"); var target = targets[i];
                if (!Regex.IsMatch(id,"\\A[0-9a-f]{64}\\z",RegexOptions.CultureInvariant) || Text(item,"mode") != ModeText(target.Mode) ||
                    !item.GetProperty("parentDev").TryGetUInt32(out uint dev) || dev != target.Parent.Dev ||
                    !item.GetProperty("parentIno").TryGetUInt64(out ulong ino) || ino != target.Parent.Ino) throw Invalid();
                result[i++]=id;
            }
            return result;
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or ArgumentException) { throw Invalid(); }
    }
    static void Exact(JsonElement value, string[] names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw Invalid();
        var fields = value.EnumerateObject().ToArray();
        if (fields.Length != names.Length || fields.Select(p=>p.Name).Distinct(StringComparer.Ordinal).Count() != names.Length || fields.Any(p=>!names.Contains(p.Name,StringComparer.Ordinal))) throw Invalid();
    }
    static string Text(JsonElement value,string name) => value.GetProperty(name).ValueKind == JsonValueKind.String ? value.GetProperty(name).GetString()! : throw Invalid();

    static async Task<string> PrepareAsync(string request, CancellationToken token)
    {
        // Fixed installed sibling; no PATH search, environment helper or shell.
        string worker = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../worker/mac-worker"));
        string? source = null;
        if (!File.Exists(worker))
        {
            // Preserve the existing development source convention. This is not
            // a new helper override; source must exist before launching Python.
            string project = Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PROJECT") ?? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../../../"));
            source = Path.Combine(project,"src/MacWorker/mac_worker.py");
            worker = (Environment.GetEnvironmentVariable("WECHAT_COLLECTOR_PYTHON") ?? "/usr/bin/python3");
            if (!File.Exists(source) || !File.Exists(worker)) throw Invalid();
        }
        var start = new ProcessStartInfo(worker) { UseShellExecute=false, RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true };
        if(source is not null)start.ArgumentList.Add(source);
        start.ArgumentList.Add("--archive-lock");start.Environment.Clear();start.Environment["PATH"]="/usr/bin:/bin";
        using var process = new Process { StartInfo=start };
        token.ThrowIfCancellationRequested();
        try { if (!process.Start()) throw Invalid(); }
        catch (System.ComponentModel.Win32Exception) { throw Invalid(); }
        void Stop() { try { if (!process.HasExited) process.Kill(entireProcessTree:false); } catch (InvalidOperationException) { } }
        using var registration=token.Register(Stop);
        try
        {
            var output=Bounded(process.StandardOutput.BaseStream,8192,token);
            var errors=Bounded(process.StandardError.BaseStream,0,token);
            await process.StandardInput.WriteLineAsync(request.AsMemory(),token);process.StandardInput.Close();
            // An overlong/noisy child is stopped immediately, even if its other
            // pipe remains open. The only permitted successful stderr is empty.
            foreach(var pipe in new[]{output,errors})
                _=pipe.ContinueWith(t=>{_ = t.Exception;if(t.IsFaulted)Stop();},TaskContinuationOptions.ExecuteSynchronously);
            var read=Task.WhenAll(output,errors);
            await read;await process.WaitForExitAsync(token);
            if(process.ExitCode!=0)throw Invalid();
            return new UTF8Encoding(false,true).GetString(await output);
        }
        finally
        {
            Stop();await process.WaitForExitAsync(CancellationToken.None);
        }
    }
    static async Task<byte[]> Bounded(Stream source,int limit,CancellationToken token)
    {
        using var memory=new MemoryStream();byte[] buffer=new byte[1024];
        for(;;){int n=await source.ReadAsync(buffer,token);if(n==0)return memory.ToArray();if(memory.Length+n>limit)throw Invalid();memory.Write(buffer,0,n);}
    }
    void CheckDirectories()
    {
        coordination!.Check();
        foreach(int fd in coordination.Fds.TakeLast(privateDirectoryCount)) Native.Private(fd,uid,true);
        foreach(int fd in coordination.Fds.SkipLast(privateDirectoryCount))
        {
            var pin=Native.FStat(fd);
            if(pin.Uid!=0 && pin.Uid!=uid || (pin.Mode&0x12)!=0 && !(pin.Uid==0 && (pin.Mode&0x200)!=0))throw Invalid();
        }
    }
    public void CheckCurrent()
    {
        lock(gate)
        {
            if(disposed || Native.GetPid()!=pid || Native.OrdinaryUid()!=uid)throw Invalid();
            CheckDirectories();
            foreach(var node in locks){Match(node.Pin,Native.Private(node.Fd,uid,false));Match(node.Pin,Native.StatAt(coordination!.Fd,node.Name));}
            foreach(var target in targets)target.Check();
        }
    }
    public void Dispose()
    {
        lock(gate)
        {
            if(disposed)return;disposed=true;
            // close releases this process's references; never unlink persistent
            // nodes and never issue LOCK_UN on a shared post-fork description.
            foreach(var node in locks.AsEnumerable().Reverse())Native.Close(node.Fd);locks.Clear();
            coordination?.Dispose();coordination=null;
            foreach(var target in targets)target.Dispose();targets.Clear();
        }
    }
    public ValueTask DisposeAsync(){Dispose();return ValueTask.CompletedTask;}
    sealed class LockNode(int fd,string name){internal readonly int Fd=fd;internal readonly string Name=name;internal Native.Stat Pin;}

    static string Canonical(string path)
    {
        if(path is null || path.Length is < 2 or > 4096 || path[0]!='/' || path.Contains('\0') || path.Split('/').Any(p=>p is "." or ".."))throw Invalid();
        try { _=new UTF8Encoding(false,true).GetBytes(path); } catch(EncoderFallbackException) { throw Invalid(); }
        string value="/"+string.Join('/',path.Split('/',StringSplitOptions.RemoveEmptyEntries));
        string top="/"+value.Split('/')[1];
        if(top is "/tmp" or "/var" or "/etc")
        {
            var pin=Native.LStat(top);
            if((pin.Mode & 0xf000)==0xa000)
            {
                if(pin.Uid!=0 || new DirectoryInfo(top).LinkTarget!="private"+top)throw Invalid();
                value="/private"+value;
            }
        }
        return value;
    }
    sealed partial class Chain : IDisposable
    {
        internal readonly List<int> Fds=[];
        readonly List<(int Parent,string Name,Native.Stat Pin)> entries=[];
        internal IEnumerable<Native.Stat> Pins => Fds.Select(Native.FStat);
        internal int Fd=>Fds[^1];
        internal bool Complete { get; private set; } = true;
        internal string? MissingName { get; private set; }
        internal Chain(string path,bool missingOk=false)
        {
            try
            {
                int root=Native.Open("/",Native.DirectoryFlags);if(root<0)throw Invalid();Fds.Add(root);
                foreach(string part in path.Split('/',StringSplitOptions.RemoveEmptyEntries))
                {
                    int parent=Fd;int fd=Native.OpenAt(parent,part,Native.DirectoryFlags);
                    if(fd<0){if(missingOk && Marshal.GetLastPInvokeError()==2){Complete=false;MissingName=part;break;}throw Invalid();}Fds.Add(fd);
                    entries.Add((parent,part,Native.FStat(fd)));
                }
                Check();
            }
            catch{Dispose();throw;}
        }
        internal void Check()
        {
            for(int i=0;i<entries.Count;i++){var entry=entries[i];Match(entry.Pin,Native.FStat(Fds[i+1]));Match(entry.Pin,Native.StatAt(entry.Parent,entry.Name));}
            foreach(int fd in Fds)Native.CheckFlags(fd,false);
        }
        public void Dispose(){foreach(int fd in Fds.AsEnumerable().Reverse())Native.Close(fd);Fds.Clear();}
    }
    sealed class Target : IDisposable
    {
        internal readonly string Path;
        internal readonly ArchiveLeaseMode Mode;
        internal readonly Native.Stat Parent;
        internal Native.Stat? Existing;
        readonly string leaf;
        Chain? chain;
        int targetFd=-1;
        internal Target(ArchiveLeaseRequest request,uint uid)
        {
            try
            {
                Path=Canonical(request.Path);Mode=request.Mode;
                string parent=System.IO.Path.GetDirectoryName(Path)!;leaf=System.IO.Path.GetFileName(Path);
                if(parent.Length==0 || leaf.Length==0)throw Invalid();
                chain=new Chain(parent);Parent=Native.FStat(chain.Fd);
                if(Parent.Uid!=uid || (Parent.Mode&0x12)!=0)throw Invalid();
                targetFd=Native.OpenAt(chain.Fd,leaf,Native.DirectoryFlags);
                if(targetFd<0){if(Marshal.GetLastPInvokeError()!=2 || Mode==ArchiveLeaseMode.Shared)throw Invalid();}
                else {Existing=Native.FStat(targetFd);if(Existing.Value.Uid!=uid || (Existing.Value.Mode&0x12)!=0)throw Invalid();}
                Check();
            }
            catch{Dispose();throw;}
        }
        internal bool ContainsParent(Native.Stat pin)=>chain!.Pins.Any(p=>SameIdentity(p,pin));
        internal void Check()
        {
            chain!.Check();Match(Parent,Native.FStat(chain.Fd));
            if(!Native.TryStatAt(chain.Fd,leaf,out var current)) {if(Existing is not null)throw Invalid();return;}
            if((current.Mode&0xf000)!=0x4000 || current.Uid!=Parent.Uid || (current.Mode&0x12)!=0)throw Invalid();
            if(Existing is {} pin){Match(pin,current);Match(pin,Native.FStat(targetFd));}
            else{targetFd=Native.OpenAt(chain.Fd,leaf,Native.DirectoryFlags);if(targetFd<0)throw Invalid();Existing=Native.FStat(targetFd);Match(current,Existing.Value);}
        }
        public void Dispose(){if(targetFd>=0){Native.Close(targetFd);targetFd=-1;}chain?.Dispose();chain=null;}
    }
    static partial class Native
    {
        const string Lib="/usr/lib/libSystem.B.dylib";
        internal const int DirectoryFlags=0x100000|0x100|4|0x1000000;
        internal const int FileFlags=2|0x100|4|0x1000000;
        [StructLayout(LayoutKind.Explicit,Size=144)]
        internal struct Stat
        {
            [FieldOffset(0)]internal uint Dev;
            [FieldOffset(4)]internal ushort Mode;
            [FieldOffset(6)]internal ushort NLink;
            [FieldOffset(8)]internal ulong Ino;
            [FieldOffset(16)]internal uint Uid;
            [FieldOffset(20)]internal uint Gid;
            [FieldOffset(24)]internal int RDev;
            [FieldOffset(32)]internal long ATime;
            [FieldOffset(40)]internal long ATimeNs;
            [FieldOffset(48)]internal long MTime;
            [FieldOffset(56)]internal long MTimeNs;
            [FieldOffset(64)]internal long CTime;
            [FieldOffset(72)]internal long CTimeNs;
            [FieldOffset(80)]internal long BirthTime;
            [FieldOffset(88)]internal long BirthTimeNs;
            [FieldOffset(96)]internal long Size;
            [FieldOffset(104)]internal long Blocks;
            [FieldOffset(112)]internal int BlockSize;
            [FieldOffset(116)]internal uint Flags;
            [FieldOffset(120)]internal uint Gen;
            [FieldOffset(124)]internal int Spare;
            [FieldOffset(128)]internal long QSpare1;
            [FieldOffset(136)]internal long QSpare2;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct Passwd
        {
            internal IntPtr Name,Password;internal uint Uid,Gid;internal long Change;
            internal IntPtr Class,Gecos,Directory,Shell;internal long Expire;
        }
        [DllImport(Lib,EntryPoint="getuid")]static extern uint GetUid();
        [DllImport(Lib,EntryPoint="geteuid")]static extern uint GetEuid();
        [DllImport(Lib,EntryPoint="getpid")]internal static extern int GetPid();
        [DllImport(Lib,EntryPoint="getpwuid_r")]static extern int GetPwUid(uint uid,out Passwd value,IntPtr buffer,nuint size,out IntPtr result);
        [DllImport(Lib,EntryPoint="open",SetLastError=true)]internal static extern int Open([MarshalAs(UnmanagedType.LPUTF8Str)]string path,int flags);
        [DllImport(Lib,EntryPoint="openat",SetLastError=true)]internal static extern int OpenAt(int parent,[MarshalAs(UnmanagedType.LPUTF8Str)]string name,int flags);
        [DllImport(Lib,EntryPoint="close")]internal static extern int Close(int fd);
        [DllImport(Lib,EntryPoint="fcntl",SetLastError=true)]static extern int GetFcntl(int fd,int command);
        [DllImport(Lib,EntryPoint="flock",SetLastError=true)]internal static extern int Flock(int fd,int operation);
        [DllImport(Lib,EntryPoint="fstat",SetLastError=true)]static extern int FStatArm(int fd,out Stat value);
        [DllImport(Lib,EntryPoint="fstat$INODE64",SetLastError=true)]static extern int FStatIntel(int fd,out Stat value);
        [DllImport(Lib,EntryPoint="fstatat",SetLastError=true)]static extern int StatAtArm(int fd,[MarshalAs(UnmanagedType.LPUTF8Str)]string name,out Stat value,int flags);
        [DllImport(Lib,EntryPoint="fstatat$INODE64",SetLastError=true)]static extern int StatAtIntel(int fd,[MarshalAs(UnmanagedType.LPUTF8Str)]string name,out Stat value,int flags);
        [DllImport(Lib,EntryPoint="lstat",SetLastError=true)]static extern int LStatArm([MarshalAs(UnmanagedType.LPUTF8Str)]string path,out Stat value);
        [DllImport(Lib,EntryPoint="lstat$INODE64",SetLastError=true)]static extern int LStatIntel([MarshalAs(UnmanagedType.LPUTF8Str)]string path,out Stat value);
        [DllImport(Lib,EntryPoint="acl_get_fd_np",SetLastError=true)]static extern IntPtr GetAcl(int fd,int type);
        [DllImport(Lib,EntryPoint="acl_get_entry",SetLastError=true)]static extern int GetAclEntry(IntPtr acl,int entry,out IntPtr result);
        [DllImport(Lib,EntryPoint="acl_free")]static extern int FreeAcl(IntPtr acl);
        internal static uint OrdinaryUid(){uint uid=GetUid();if(uid==0 || uid!=GetEuid())throw Invalid();return uid;}
        internal static string UserHome(uint uid)
        {
            IntPtr buffer=Marshal.AllocHGlobal(32768);
            try{if(GetPwUid(uid,out var record,buffer,32768,out var result)!=0 || result==IntPtr.Zero || record.Uid!=uid || record.Directory==IntPtr.Zero)throw Invalid();return Marshal.PtrToStringUTF8(record.Directory)??throw Invalid();}
            finally{Marshal.FreeHGlobal(buffer);}
        }
        internal static Stat FStat(int fd)
        {
            Stat value;int result=RuntimeInformation.ProcessArchitecture==Architecture.X64?FStatIntel(fd,out value):FStatArm(fd,out value);
            if(result!=0)throw Invalid();return value;
        }
        internal static Stat LStat(string path)
        {
            Stat value;int result=RuntimeInformation.ProcessArchitecture==Architecture.X64?LStatIntel(path,out value):LStatArm(path,out value);
            if(result!=0)throw Invalid();return value;
        }
        internal static bool TryStatAt(int fd,string name,out Stat value)
        {
            int result=RuntimeInformation.ProcessArchitecture==Architecture.X64?StatAtIntel(fd,name,out value,0x20):StatAtArm(fd,name,out value,0x20);
            if(result==0)return true;if(Marshal.GetLastPInvokeError()==2)return false;throw Invalid();
        }
        internal static Stat StatAt(int fd,string name){if(!TryStatAt(fd,name,out var value))throw Invalid();return value;}
        internal static void CheckFlags(int fd,bool writable)
        {
            int descriptor=GetFcntl(fd,1),status=GetFcntl(fd,3);
            if(descriptor<0 || (descriptor&1)==0 || status<0 || (status&3)!=(writable?2:0))throw Invalid();
        }
        internal static Stat Private(int fd,uint uid,bool directory)
        {
            var value=FStat(fd);CheckFlags(fd,!directory);
            if(value.Uid!=uid || (value.Mode&0xfff)!=(directory?0x1c0:0x180) ||
                (value.Mode&0xf000)!=(directory?0x4000:0x8000) || (!directory && (value.NLink!=1 || value.Size!=0)))throw Invalid();
            IntPtr acl=GetAcl(fd,256);
            if(acl==IntPtr.Zero){if(Marshal.GetLastPInvokeError()!=2)throw Invalid();}
            else
            {
                try{if(GetAclEntry(acl,0,out _) ==0 || Marshal.GetLastPInvokeError()!=22)throw Invalid();}
                finally{FreeAcl(acl);}
            }
            return value;
        }
    }
}
