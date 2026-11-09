using System.Runtime.InteropServices;

namespace WechatCollector.Mac;

public sealed partial class MacArchiveLease
{
    internal enum ClonePathRelation { Disjoint, SamePhysical, SourceAncestorOfDestination, DestinationAncestorOfSource, UnresolvedMayAlias }

    internal static Task<ClonePaths> PrepareClonePathsAsync(string source,string state,CancellationToken token)
    {
        uint uid=Native.OrdinaryUid();string home=Canonical(Native.UserHome(uid));
        return PrepareClonePathsCoreAsync(source,state,Path.Combine(home,"Library/Application Support/WechatCollectorMac/archive-locks/parent-leaf-v1"),NormalizeCloneNamesAsync,token);
    }
    internal static Task<ClonePaths> PrepareClonePathsForTestsAsync(string source,string state,string coordinationRoot,
        Func<IReadOnlyList<string>,CancellationToken,Task<int[]>> normalize,CancellationToken token) =>
        PrepareClonePathsCoreAsync(source,state,coordinationRoot,normalize,token);

    static async Task<ClonePaths> PrepareClonePathsCoreAsync(string source,string state,string root,
        Func<IReadOnlyList<string>,CancellationToken,Task<int[]>> normalize,CancellationToken token)
    {
        if(!OperatingSystem.IsMacOS())throw new PlatformNotSupportedException();
        token.ThrowIfCancellationRequested();uint uid=Native.OrdinaryUid();
        ClonePaths? paths=null;
        try
        {
            paths=new ClonePaths(Canonical(Path.GetFullPath(source)),Canonical(Path.GetFullPath(state)),Canonical(root),uid);
            string[] names=paths.AllNames().Distinct(StringComparer.Ordinal).ToArray();
            if(normalize is null || names.Length is <1 or >2048)throw Invalid();
            int[] labels=await normalize(names,token);token.ThrowIfCancellationRequested();
            if(labels is null || labels.Length!=names.Length)throw Invalid();
            int next=0;foreach(int label in labels){if(label<0 || label>next)throw Invalid();if(label==next)next++;}
            paths.SetNames(names,labels);
            paths.CheckAll();paths.CheckReserved();paths.CreateState(token);paths.CheckAll();
            paths.RefreshRelation();
            token.ThrowIfCancellationRequested();return paths;
        }
        catch{paths?.Dispose();throw;}
    }

    // Each observation owns its whole read-only chain. Missing suffixes never
    // become present implicitly; only our mkdir pins or explicit EX adoption advance them.
    sealed class CloneRole : IDisposable
    {
        internal readonly string Path;
        internal readonly string[] Parts;
        internal readonly Chain Chain;
        internal readonly uint Uid;
        readonly bool parentPolicy;
        internal int Count => Chain.Fds.Count-1;
        internal bool Complete => Count==Parts.Length;
        internal Native.Stat Last => Native.FStat(Chain.Fd);
        internal IEnumerable<string> Missing => Parts.Skip(Count);
        internal CloneRole(string path,uint uid,bool parentPolicy=false)
        {
            Path=path;Uid=uid;this.parentPolicy=parentPolicy;Parts=path.Split('/',StringSplitOptions.RemoveEmptyEntries);
            Chain=new Chain(path,true);
            try{ValidateEnd();Check();}catch{Dispose();throw;}
        }
        internal void ValidateEnd()
        {
            var pin=Last;
            if(pin.Uid!=Uid || (pin.Mode&0x12)!=0)throw Invalid();
            // A's selected target policy includes its immediate existing parent.
            if(parentPolicy && Complete && Count>0){var parent=Native.FStat(Chain.Fds[^2]);if(parent.Uid!=Uid || (parent.Mode&0x12)!=0)throw Invalid();}
        }
        internal void Check(bool absent=true)
        {
            Chain.Check();ValidateEnd();
            if(absent && !Complete && Native.TryStatAt(Chain.Fd,Parts[Count],out _))throw Invalid();
        }
        internal void AppendOwned(string name,int fd,Native.Stat pin)
        {
            if(Complete || Parts[Count]!=name)throw Invalid();
            Chain.Append(name,fd,pin);
        }
        public void Dispose()=>Chain.Dispose();
    }

    internal sealed partial class ClonePaths : IDisposable
    {
        readonly object operation=new();
        readonly uint uid;readonly int pid;
        readonly CloneRole source,state,destination,reserved,homeRole;
        readonly Native.Stat home;
        Dictionary<string,int> names=new(StringComparer.Ordinal);
        readonly List<(int Fd,Native.Stat Pin)> created=[];
        bool disposed;
        internal string SourcePath=>source.Path;
        internal string StatePath=>state.Path;
        internal string DestinationPath=>destination.Path;
        internal bool SourceExists { get; }
        internal ClonePathRelation PhysicalRelation { get; private set; }

        internal ClonePaths(string sourcePath,string statePath,string root,uint uid)
        {
            this.uid=uid;pid=Native.GetPid();
            var opened=new List<CloneRole>();
            try
            {
                homeRole=new CloneRole(Canonical(Native.UserHome(uid)),uid);opened.Add(homeRole);
                if(!homeRole.Complete)throw Invalid();home=homeRole.Last;
                source=new CloneRole(sourcePath,uid,true);opened.Add(source);
                state=new CloneRole(statePath,uid);opened.Add(state);
                destination=new CloneRole(Canonical(Path.Combine(statePath,"archive")),uid,true);opened.Add(destination);
                reserved=new CloneRole(root,uid);opened.Add(reserved);
                SourceExists=source.Complete;
                // Before normalization we can already reject actual identity overlap.
                CheckAll();CheckActualReserved();
            }
            catch{foreach(var role in opened.AsEnumerable().Reverse())role.Dispose();throw;}
        }
        IEnumerable<CloneRole> Roles => new[]{source,state,destination,reserved,homeRole};
        internal void SetNames(string[] raw,int[] labels)=>names=raw.Select((n,i)=>(n,labels[i])).ToDictionary(p=>p.n,p=>p.Item2,StringComparer.Ordinal);
        internal void RefreshRelation()=>PhysicalRelation=Relation(source,destination);
        internal IEnumerable<string> AllNames()=>Roles.SelectMany(r=>r.Parts);
        void Alive(){if(disposed || Native.GetPid()!=pid || Native.OrdinaryUid()!=uid)throw Invalid();}
        internal void CheckAll()
        {
            Alive();foreach(var r in Roles)r.Check();
            CheckCreated();
            CheckActualReserved();
        }
        void CheckCreated(){foreach(var node in created)Match(node.Pin,Native.Private(node.Fd,uid,true));}
        static bool Contains(CloneRole role,Native.Stat pin)=>role.Chain.Pins.Any(p=>SameIdentity(p,pin));
        void CheckActualReserved()
        {
            foreach(var role in new[]{source,destination})
            {
                if(role.Path=="/" || role.Complete && SameIdentity(role.Last,home) || Overlap(role.Path,reserved.Path))throw Invalid();
                if(role.Complete && Contains(reserved,role.Last) || reserved.Complete && Contains(role,reserved.Last))throw Invalid();
            }
        }
        // Deepest common held identity handles firmlink spellings. Existing
        // different nodes are disjoint even if Python assigns equal name labels.
        (string[] A,string[] B,int AExisting,int BExisting) Suffixes(CloneRole a,CloneRole b)
        {
            var aa=a.Chain.Pins.ToArray();var bb=b.Chain.Pins.ToArray();int ai=0,bi=0,score=-1;
            for(int i=0;i<aa.Length;i++)for(int j=0;j<bb.Length;j++)if(i+j>score && SameIdentity(aa[i],bb[j])){ai=i;bi=j;score=i+j;}
            return(a.Parts.Skip(ai).ToArray(),b.Parts.Skip(bi).ToArray(),a.Count-ai,b.Count-bi);
        }
        bool PotentialOverlap(CloneRole a,CloneRole b)
        {
            var s=Suffixes(a,b);
            for(int i=0;i<Math.Min(s.A.Length,s.B.Length);i++)
            {
                if(i<s.AExisting && i<s.BExisting)return false;
                if(names[s.A[i]]!=names[s.B[i]])return false;
            }
            return true;
        }
        internal void CheckReserved()
        {
            foreach(var role in new[]{source,destination})if(PotentialOverlap(role,reserved))throw Invalid();
        }
        ClonePathRelation Relation(CloneRole a,CloneRole b)
        {
            if(a.Complete && b.Complete && SameIdentity(a.Last,b.Last))return ClonePathRelation.SamePhysical;
            if(a.Complete && Contains(b,a.Last))return ClonePathRelation.SourceAncestorOfDestination;
            if(b.Complete && Contains(a,b.Last))return ClonePathRelation.DestinationAncestorOfSource;
            return PotentialOverlap(a,b)?ClonePathRelation.UnresolvedMayAlias:ClonePathRelation.Disjoint;
        }
        // A common exact missing prefix is safe only while it is a strict
        // source ancestor. Equal folded but differently spelled edges refuse.
        void CheckCreationRange()
        {
            if(source.Complete && Contains(state,source.Last))throw Invalid();
            var s=Suffixes(source,state);
            for(int i=0;i<Math.Min(s.A.Length,s.B.Length);i++)
            {
                if(i<s.AExisting && i<s.BExisting)return;
                if(names[s.A[i]]!=names[s.B[i]])return;
                if(s.A[i]!=s.B[i])throw Invalid();
            }
            if(s.A.Length<=s.B.Length)throw Invalid();
        }
        internal void CreateState(CancellationToken token)
        {
            if(!state.Complete)CheckCreationRange();
            while(!state.Complete)
            {
                token.ThrowIfCancellationRequested();CheckAll();CheckReserved();CheckCreationRange();
                int parent=state.Chain.Fd;string name=state.Parts[state.Count];var parentPin=state.Last;
                if(Native.MkdirAt(parent,name,0x1c0)!=0)throw Invalid();
                int fd=Native.OpenAt(parent,name,Native.DirectoryFlags);if(fd<0)throw Invalid();
                try
                {
                    var pin=Native.Private(fd,uid,true);Match(pin,Native.StatAt(parent,name));
                    // Validate all prior entry pins before retaining the new node.
                    foreach(var role in Roles)role.Chain.Check();
                    if(source.Complete && Contains(source,pin))throw Invalid();
                    state.AppendOwned(name,fd,pin);created.Add((fd,pin));fd=-1;
                    foreach(var role in new[]{source,destination,reserved})
                    {
                        if(!role.Complete && SameIdentity(role.Last,parentPin) && role.Parts[role.Count]==name)
                        {
                            int own=Native.OpenAt(role.Chain.Fd,name,Native.DirectoryFlags);if(own<0)throw Invalid();
                            try{Match(pin,Native.FStat(own));Match(pin,Native.StatAt(role.Chain.Fd,name));role.AppendOwned(name,own,pin);own=-1;}
                            finally{if(own>=0)Native.Close(own);}
                        }
                    }
                }
                finally{if(fd>=0)Native.Close(fd);}
            }
        }
        internal void CheckCurrent(){lock(operation){CheckAll();CheckReserved();}}
        internal void AdoptDestinationAfterWaiting(MacArchiveLease authority)
        {
            lock(operation)
            {
                Alive();if(authority is null)throw Invalid();
                lock(authority.gate)
                {
                    source.Check();state.Check();homeRole.Check();reserved.Check(false);CheckCreated();CheckActualReserved();CheckReserved();
                    if(authority.disposed || authority.pid!=pid || authority.uid!=uid)throw Invalid();
                    var destinations=authority.targets.Where(t=>t.Path==DestinationPath).ToArray();
                    if(!destinations.Any(t=>t.Mode==ArchiveLeaseMode.Exclusive))throw Invalid();
                    foreach(var target in destinations)
                    {
                        Match(target.Parent,state.Last);
                        if(destination.Complete){if(target.Existing is not {} pin)throw Invalid();Match(pin,destination.Last);}
                    }
                    if(SourceExists)
                    {
                        var sources=authority.targets.Where(t=>t.Path==SourcePath).ToArray();
                        if(sources.Length==0)throw Invalid();
                        foreach(var target in sources)
                        {
                            if(target.Existing is not {} pin)throw Invalid();
                            Match(pin,source.Last);Match(target.Parent,Native.FStat(source.Chain.Fds[^2]));
                        }
                    }
                    authority.CheckDirectories();
                    // The preparation process may have created the previously
                    // absent reserved suffix. Accept it only from this live lease.
                    if(authority.coordination is null || authority.coordination.Fds.Count-1!=reserved.Parts.Length)throw Invalid();
                    for(int i=0;i<reserved.Chain.Fds.Count;i++)Match(Native.FStat(reserved.Chain.Fds[i]),Native.FStat(authority.coordination.Fds[i]));
                    while(!reserved.Complete)
                    {
                        string name=reserved.Parts[reserved.Count];int fd=Native.OpenAt(reserved.Chain.Fd,name,Native.DirectoryFlags);if(fd<0)throw Invalid();
                        try{var pin=Native.FStat(fd);Match(pin,Native.FStat(authority.coordination.Fds[reserved.Count+1]));Match(pin,Native.StatAt(reserved.Chain.Fd,name));reserved.AppendOwned(name,fd,pin);fd=-1;}finally{if(fd>=0)Native.Close(fd);}
                    }
                    reserved.Check();
                    // All source/state/reserved observations are now validated
                    // before Target.Check may open an appeared destination.
                    authority.CheckCurrent();
                    destination.Check(false);
                    if(!destination.Complete && Native.TryStatAt(state.Chain.Fd,"archive",out var current))
                    {
                        int fd=Native.OpenAt(state.Chain.Fd,"archive",Native.DirectoryFlags);if(fd<0)throw Invalid();
                        try{var pin=Native.FStat(fd);Match(current,pin);if(pin.Uid!=uid || (pin.Mode&0x12)!=0)throw Invalid();foreach(var target in destinations){if(target.Existing is not {} expected)throw Invalid();Match(expected,pin);}destination.AppendOwned("archive",fd,pin);fd=-1;}finally{if(fd>=0)Native.Close(fd);}
                    }
                    CheckAll();CheckReserved();PhysicalRelation=Relation(source,destination);
                }
            }
        }
        // Readiness is only the historical regular index-exists contract. No content
        // hash, SQLite open or health assertion belongs to this metadata check.
        internal bool DestinationIndexExists()
        {
            lock(operation){CheckAll();return RegularEntryExists(destination,"index.db");}
        }
        internal bool SourceFileExists(string name)
        {
            if(name is not ("index.db" or "capture-consent.json"))throw Invalid();
            lock(operation){CheckAll();return RegularEntryExists(source,name);}
        }
        bool RegularEntryExists(CloneRole role,string name)
        {
            if(!role.Complete)return false;
            if(!Native.TryStatAt(role.Chain.Fd,name,out var pin))return false;
            if((pin.Mode&0xf000)!=0x8000 || pin.Uid!=uid)throw Invalid();role.Check();return true;
        }
        internal void CreateDestination(MacArchiveLease authority,CancellationToken token)
        {
            lock(operation)
            {
                // Validate actual roles and EX ownership before mkdirat. Any newly
                // appeared entry must be re-preflighted by a subsequent invocation.
                bool existed=destination.Complete;
                AdoptDestinationAfterWaiting(authority);token.ThrowIfCancellationRequested();
                if(!existed && destination.Complete)throw Invalid();
                if(destination.Complete)return;
                if(PhysicalRelation!=ClonePathRelation.Disjoint)throw Invalid();
                if(Native.MkdirAt(state.Chain.Fd,"archive",0x1c0)!=0)throw Invalid();
                int fd=Native.OpenAt(state.Chain.Fd,"archive",Native.DirectoryFlags);if(fd<0)throw Invalid();
                try
                {
                    var pin=Native.Private(fd,uid,true);Match(pin,Native.StatAt(state.Chain.Fd,"archive"));
                    source.Check();state.Check();reserved.Check();homeRole.Check();CheckCreated();
                    authority.CheckCurrent();
                    destination.AppendOwned("archive",fd,pin);created.Add((fd,pin));fd=-1;
                }
                finally{if(fd>=0)Native.Close(fd);}
                AdoptDestinationAfterWaiting(authority);CheckAll();
            }
        }
        public void Dispose(){lock(operation){if(disposed)return;disposed=true;foreach(var role in Roles.Reverse())role.Dispose();}}
    }
    sealed partial class Chain
    {
        internal void Append(string name,int fd,Native.Stat pin)
        {
            int parent=Fd;Match(pin,Native.FStat(fd));Match(pin,Native.StatAt(parent,name));Native.CheckFlags(fd,false);
            entries.Add((parent,name,pin));Fds.Add(fd);Complete=true;MissingName=null;
        }
    }
    static partial class Native
    {
        [DllImport(Lib,EntryPoint="mkdirat",SetLastError=true)]internal static extern int MkdirAt(int parent,[MarshalAs(UnmanagedType.LPUTF8Str)]string name,ushort mode);
    }
}
