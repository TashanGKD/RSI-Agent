import AppKit
import OSAKit
import Darwin

// The signed Native executable supplies helper pins. Resource hashes never grant root authority.
final class MacConnectionBootstrap {
    enum Failure: Error { case unsupported }
    enum AuthorizationOutcome: String { case success, userCancelled, failed }
    private static func owner() throws -> (uid_t, String) {
        let uid = getuid()
        guard uid != 0, geteuid() == uid else { throw Failure.unsupported }
        var entry = passwd(), found: UnsafeMutablePointer<passwd>?
        var buffer = [CChar](repeating: 0, count: 65536)
        var home: String?
        let code = buffer.withUnsafeMutableBufferPointer { p -> Int32 in
            let result = getpwuid_r(uid, &entry, p.baseAddress, p.count, &found)
            if result == 0, found != nil, entry.pw_uid == uid, let raw = entry.pw_dir { home = String(cString: raw) }
            return result
        }
        guard code == 0, let home, home.hasPrefix("/"), home != "/", !home.utf8.contains(where: { $0 < 32 || $0 == 127 }),
              URL(fileURLWithPath: home).standardizedFileURL.path == home else { throw Failure.unsupported }
        return (uid, home)
    }
    static func command(operation: String) throws -> String {
        guard operation.range(of: #"\A[0-9a-f]{32}\z"#, options: .regularExpression) != nil,
              FileManager.default.isExecutableFile(atPath: "/usr/bin/perl") else { throw Failure.unsupported }
        let (uid, home) = try owner()
        let program = build(uid: uid, home: home, operation: operation, digest: MacConnectionBuildPins.helperSHA256,
                            bytes: MacConnectionBuildPins.helperBytes, requiredUID: 0, stageBase: "/private/tmp", sourceOverride: nil, osHome: true, expectedExit: 0)
        return "/usr/bin/env -i /usr/bin/perl -T -e " + shellQuote(program)
    }
    static func authorize(operation: String) -> AuthorizationOutcome {
        guard let command = try? command(operation: operation), supported() else { return .failed }
        let source = "do shell script " + appleQuote(command) + " with administrator privileges"
        return ScriptInvocation().execute(source) // Launch outcome only; authenticated Go terminal owns cleanup/result.
    }
    // This object is local to one call on the existing serialized authorization queue.
    // No interpreter, descriptor or error dictionary survives its autoreleasepool.
    private final class ScriptInvocation {
        init() {}
        #if MAC_CONNECTION_FIXTURE
        private var fixtureCase: FixtureScriptCase?
        private var overlap: FixtureScriptOverlap?
        var observation: [String: Any] = ["success": false, "languageAvailable": false,
            "languageThreadSafe": false, "explicitAppleScript": false, "scriptCreated": false,
            "executed": false, "fixtureForcedDenial": false]
        init(fixture: FixtureScriptCase, overlap: FixtureScriptOverlap? = nil) {
            fixtureCase = fixture; self.overlap = overlap
        }
        #endif
        func execute(_ source: String) -> AuthorizationOutcome {
            #if MAC_CONNECTION_FIXTURE
            weak var observedScript: OSAScript?
            weak var observedInstance: OSALanguageInstance?
            observation["constructedOnMainThread"] = Thread.isMainThread
            #endif
            let outcome: AuthorizationOutcome = autoreleasepool {
                #if MAC_CONNECTION_FIXTURE
                if fixtureCase == .missingLanguage { observation["fixtureForcedDenial"] = true; return .failed }
                #endif
                guard let language = OSALanguage(forName: "AppleScript") else { return .failed }
                #if MAC_CONNECTION_FIXTURE
                observation["languageAvailable"] = true
                observation["languageThreadSafe"] = language.isThreadSafe
                observation["explicitAppleScript"] = language.name == "AppleScript"
                if fixtureCase == .unsafeLanguage { observation["fixtureForcedDenial"] = true; return .failed }
                #endif
                guard language.isThreadSafe else { return .failed }
                let instance = OSALanguageInstance(language: language)
                let script = OSAScript(source: source, from: nil, languageInstance: instance, using: [])
                #if MAC_CONNECTION_FIXTURE
                observedScript = script; observedInstance = instance
                observation["scriptCreated"] = true
                observation["privateComponent"] = instance.componentInstance != language.componentInstance
                observation["explicitInstance"] = script.languageInstance === instance
                if let overlap, !overlap.arrive(instance) { return .failed }
                #endif
                var error: NSDictionary?
                #if MAC_CONNECTION_FIXTURE
                observation["executedOnMainThread"] = Thread.isMainThread
                let result = script.executeAndReturnError(&error)
                observation["executed"] = true
                observation["errorPresent"] = error != nil
                observation["resultInt32"] = Int(result?.int32Value ?? -1)
                #else
                _ = script.executeAndReturnError(&error)
                #endif
                guard let error else { return .success }
                return (error[OSAScriptErrorNumberKey] as? NSNumber)?.intValue == -128 ? .userCancelled : .failed
            }
            #if MAC_CONNECTION_FIXTURE
            observation["success"] = outcome == .success
            observation["outcome"] = outcome.rawValue
            observation["scriptReleased"] = observedScript == nil
            observation["instanceReleased"] = observedInstance == nil
            #endif
            return outcome
        }
    }
    #if MAC_CONNECTION_FIXTURE
    // Closed generated cases only: no arbitrary source, language, command, URL or privilege selector.
    enum FixtureScriptCase { case literal, executionFailure, childFailure, userCancellation, missingLanguage, unsafeLanguage }
    private final class FixtureScriptOverlap {
        private let lock = NSLock(), ready = DispatchSemaphore(value: 0)
        private var identities = Set<ObjectIdentifier>(), arrivals = 0
        func arrive(_ instance: OSALanguageInstance) -> Bool {
            lock.lock(); identities.insert(ObjectIdentifier(instance)); arrivals += 1
            if arrivals == 2 { ready.signal(); ready.signal() }; lock.unlock()
            return ready.wait(timeout: .now() + 8) == .success
        }
        var distinct: Bool { lock.lock(); defer { lock.unlock() }; return arrivals == 2 && identities.count == 2 }
    }
    private final class FixtureScriptResults: @unchecked Sendable {
        private let lock = NSLock()
        private var results: [[String: Any]] = []
        func add(_ result: [String: Any]) { lock.lock(); results.append(result); lock.unlock() }
        var values: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return results }
    }
    static func fixtureScriptProbe(_ test: FixtureScriptCase) -> [String: Any] {
        let invocation = ScriptInvocation(fixture: test)
        let source: String
        switch test {
        case .executionFailure: source = "error \"generated-c9d-private-marker\" number 77"
        case .childFailure: source = "error \"generated-c9e-private-marker\" number 70"
        case .userCancellation: source = "error number -128"
        default: source = "return 42"
        }
        _ = invocation.execute(source)
        return invocation.observation
    }
    static func fixtureScriptOverlapProbe() -> [String: Any] {
        let overlap = FixtureScriptOverlap(), results = FixtureScriptResults(), group = DispatchGroup()
        for index in 0..<2 {
            group.enter()
            DispatchQueue(label: "generated.c9d.component.\(index)").async {
                defer { group.leave() }
                let invocation = ScriptInvocation(fixture: .literal, overlap: overlap)
                _ = invocation.execute("return 42"); results.add(invocation.observation)
            }
        }
        let complete = group.wait(timeout: .now() + 10) == .success
        return ["complete": complete, "distinctInstances": overlap.distinct, "observations": results.values]
    }
    #endif
    private enum ProbeOutcome: String { case supported, failed, timedOut, cleanupUnconfirmed = "cleanup_unconfirmed" }
    private final class OwnedProbe {
        let process = Process(), finished = DispatchSemaphore(value: 0)
        init(arguments: [String]) {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/perl"); process.arguments = arguments
            process.environment = [:]; process.standardInput = FileHandle.nullDevice; process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
            // Keep this exact owned Process alive until its termination callback, even after a bounded unknown result.
            process.terminationHandler = { [self] child in finished.signal(); child.terminationHandler = nil }
        }
        func run(budget: TimeInterval, cleanupBudget: TimeInterval) -> ProbeOutcome {
            do { try process.run() } catch { process.terminationHandler = nil; return .failed }
            if finished.wait(timeout: .now() + budget) == .success { return process.terminationStatus == 0 ? .supported : .failed }
            if process.isRunning { process.terminate() }
            return finished.wait(timeout: .now() + cleanupBudget) == .success ? .timedOut : .cleanupUnconfirmed
        }
    }
    private static func supported() -> Bool {
        OwnedProbe(arguments: ["-T", "-MDigest::SHA", "-MFcntl", "-MErrno=EINTR,ECHILD", "-MTime::HiRes=clock_gettime,CLOCK_MONOTONIC", "-e", "exit 0"])
            .run(budget: 2, cleanupBudget: 0.5) == .supported
    }
    // Shared by the actual root program and generated wait-result fixtures. No blocking wait or PID discovery.
    private static let reaperSource = #"""
sub wait_observation { $!=0;my $got=waitpid($child,WNOHANG);my $status=$?;my $error=0+$!;return ($got,$status,$error); }
sub now_tick { return Time::HiRes::clock_gettime(Time::HiRes::CLOCK_MONOTONIC()); }
sub wait_tick { select(undef,undef,undef,0.05); }
sub send_owned_signal { my ($signal)=@_;return unless $owned && !$reaped;kill($signal,$child); }
sub poll_owned {
 return if !$owned || $reaped;
 my ($got,$status,$error)=wait_observation();
 if($got==$child){$child_status=$status;$reaped=1;$owned=0;return;}
 return if $got==0 || ($got<0 && $error==EINTR);
 # ECHILD or any other unknown wait result relinquishes signal authority without claiming a reap.
 $owned=0;$cleanup_unconfirmed=1;
}
sub join_until {
 my ($deadline,$observe_cancel)=@_;
 while($owned && !$reaped && now_tick()<$deadline){poll_owned();last if !$owned || $reaped || ($observe_cancel && $aborted);wait_tick();}
 return $reaped;
}
sub stop_owned {
 my ($term_budget,$kill_budget)=@_;return if $cleanup_started++;
 return if !defined($child) || $reaped;
 if(!$owned){$cleanup_unconfirmed=1;return;}
 poll_owned();return if $reaped || !$owned;
 send_owned_signal('TERM');join_until(now_tick()+$term_budget,0);
 if($owned && !$reaped){poll_owned();if($owned && !$reaped){send_owned_signal('KILL');join_until(now_tick()+$kill_budget,0);}}
 $cleanup_unconfirmed=1 unless $reaped;
}
"""#
    private static func shellQuote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'" }
    private static func appleQuote(_ value: String) -> String { "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\"" }
    private static func perlQuote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'") + "'" }
    private static func build(uid: uid_t, home: String, operation: String, digest: String, bytes: Int, requiredUID: uid_t, stageBase: String, sourceOverride: String?, osHome: Bool, expectedExit: Int) -> String {
        let source = sourceOverride ?? home + "/Library/Application Support/WechatCollectorMac/helpers/" + digest + "/wxkey"
        return #"""
use strict; use warnings; use Fcntl qw(:DEFAULT :mode); use Digest::SHA; use POSIX qw(:sys_wait_h); use Errno qw(EINTR ECHILD); use Time::HiRes ();
my $uid=\#(uid); my $need=\#(requiredUID); my $home=\#(perlQuote(home)); my $src=\#(perlQuote(source));
my $sha=\#(perlQuote(digest)); my $bytes=\#(bytes); my $nonce=\#(perlQuote(operation));
my $dir=\#(perlQuote(stageBase)) . '/wxkey-launch-' . $nonce; my $leaf=$dir . '/wxkey';
my ($dp,$fp,$child,$out,$child_status); my $reaped=0; my $owned=0; my $aborted=0; my $cleanup_unconfirmed=0; my $cleanup_started=0;
\#(reaperSource)
$SIG{TERM}=sub{$aborted=1}; $SIG{INT}=sub{$aborted=1};
sub pin { my @s=@_;return undef unless @s;return join(':',@s[0,1,2,3,4,5,7,9,10]); }
sub dirpin { my @s=@_;return undef unless @s;return join(':',@s[0,1,2,4]); }
sub same { my ($a,$b)=@_; return defined($a) && defined($b) && $a eq $b; }
sub fileok { my ($h,$owner,$mode)=@_; my @s=stat($h); die 'invalid' unless @s && S_ISREG($s[2]) && $s[3]==1 && $s[4]==$owner && ($s[2]&07777)==$mode && $s[7]>0 && $s[7]<=33554432; return pin(@s); }
my $ok=eval {
 die 'identity' unless $<==$need && $>==$need && $uid>0 && $bytes>0 && $bytes<=33554432;
 \#(osHome ? "my @pw=getpwuid($uid); die 'owner' unless @pw && $pw[7] eq $home;" : "")
 umask 077; mkdir($dir,0700) or die 'stage'; my @d=lstat($dir); $dp=dirpin(@d);
 die 'stage' unless S_ISDIR($d[2]) && $d[4]==$need && ($d[2]&07777)==0700;
 sysopen(my $in,$src,O_RDONLY|O_NONBLOCK|O_NOFOLLOW) or die 'source'; my $sp=fileok($in,$uid,0500);
 die 'size' unless (stat($in))[7]==$bytes;
 sysopen($out,$leaf,O_RDWR|O_CREAT|O_EXCL|O_NONBLOCK|O_NOFOLLOW,0600) or die 'copy'; $fp=pin(stat($out));
 my $hash=Digest::SHA->new(256); my $count=0;
 while(1) { die 'cancel' if $aborted; my $n=sysread($in,my $buf,65536); die 'read' unless defined $n; last if $n==0; $count+=$n; die 'size' if $count>$bytes; $hash->add($buf); my $at=0; while($at<$n){my $w=syswrite($out,$buf,$n-$at,$at); die 'write' unless defined($w)&&$w>0;$at+=$w;} }
 $fp=pin(stat($out)); die 'hash' unless $count==$bytes && $hash->hexdigest eq $sha;
 die 'sourcechange' unless same(fileok($in,$uid,0500),$sp) && same(pin(lstat($src)),$sp);
 seek($out,0,0) or die 'seek'; my $readback=Digest::SHA->new(256); my $again=0;
 while(1){my $n=sysread($out,my $buf,65536);die 'readback' unless defined $n;last if !$n;$again+=$n;die 'size' if $again>$bytes;$readback->add($buf);}
 die 'readback' unless $again==$bytes && $readback->hexdigest eq $sha && same(pin(stat($out)),$fp) && same(pin(lstat($leaf)),$fp) && same(dirpin(lstat($dir)),$dp);
 chmod(0500,$out)==1 or die 'mode'; $fp=fileok($out,$need,0500);
 die 'path' unless same(pin(lstat($leaf)),$fp) && same(dirpin(lstat($dir)),$dp); close($in); close($out);
 die 'cancel' if $aborted; $child=fork(); die 'fork' unless defined $child;
 if($child==0){%ENV=();open(STDIN,'<','/dev/null') or POSIX::_exit(70);open(STDOUT,'>','/dev/null') or POSIX::_exit(70);open(STDERR,'>','/dev/null') or POSIX::_exit(70);exec {$leaf} $leaf,'bootstrap','--operation',$nonce or POSIX::_exit(70);}
 $owned=1;join_until(now_tick()+365,1);
 die 'deadline' unless $reaped;
 die 'child' unless defined($child_status) && $child_status==\#(expectedExit << 8); 1;
};
if(defined($out) && defined(fileno($out))){$fp=pin(stat($out));close($out);}
if(!eval{stop_owned(2,1);1}){$cleanup_unconfirmed=1;}
# Finite cleanup owns only recorded inodes; unknown replacements remain untouched.
if(!$cleanup_unconfirmed && (!defined($child) || $reaped) && defined($dp)){
 if(!same(dirpin(lstat($dir)),$dp)){$cleanup_unconfirmed=1;}
 else{
  if(defined($fp)){if(!same(pin(lstat($leaf)),$fp)){$cleanup_unconfirmed=1;}elsif(unlink($leaf)!=1){$cleanup_unconfirmed=1;}}
  if(!$cleanup_unconfirmed && !rmdir($dir)){$cleanup_unconfirmed=1;}
 }
}
if($cleanup_unconfirmed){print STDERR "cleanup_unconfirmed\n";exit 71;}
exit($ok?0:70);
"""#
    }
    #if MAC_CONNECTION_FIXTURE
    static func fixturePreflight(arguments: [String], scale: TimeInterval) -> String {
        precondition(scale > 0 && scale <= 1)
        return OwnedProbe(arguments: arguments).run(budget: 2 * scale, cleanupBudget: 0.5 * scale).rawValue
    }
    static func fixtureReaperProgram(scenario: String) -> String {
        precondition(["normal", "interrupt_then_reap", "always_interrupt", "always_alive", "lost_child", "unknown_wait", "lost_after_term", "term_reaped"].contains(scenario))
        return #"""
use strict;use warnings;use POSIX qw(:sys_wait_h);use Errno qw(EINTR ECHILD EIO);use Time::HiRes ();use JSON::PP;
my $child=424242;my $child_status;my $reaped=0;my $owned=1;my $aborted=0;my $cleanup_unconfirmed=0;my $cleanup_started=0;
\#(reaperSource)
my $scenario=\#(perlQuote(scenario));my $clock=0;my $calls=0;my @signals;
{no warnings 'redefine';
 *now_tick=sub{$clock+=0.01;return $clock;};*wait_tick=sub{};
 *send_owned_signal=sub{my($signal)=@_;die 'unowned signal' unless $owned && !$reaped;push @signals,$signal;};
 *wait_observation=sub{
  $calls++;
  return ($child,0,0) if $scenario eq 'normal' || $scenario eq 'interrupt_then_reap' && $calls>2 || $scenario eq 'term_reaped' && @signals;
  return (-1,0,EINTR) if $scenario eq 'interrupt_then_reap' || $scenario eq 'always_interrupt';
  return (-1,0,ECHILD) if $scenario eq 'lost_child' || $scenario eq 'lost_after_term' && @signals;
  return (-1,0,EIO) if $scenario eq 'unknown_wait';
  return (0,0,0);
 };
}
join_until(now_tick()+0.1,1);stop_owned(0.1,0.1);stop_owned(0.1,0.1);
print JSON::PP->new->canonical->encode({scenario=>$scenario,reaped=>$reaped,owned=>$owned,cleanup_unconfirmed=>$cleanup_unconfirmed,signals=>\@signals,calls=>$calls,elapsed=>$clock,child_status=>$child_status});
"""#
    }
    static func fixtureProgram(uid: uid_t, home: String, operation: String, digest: String, bytes: Int, stageBase: String, source: String, expectedExit: Int = 0, waitScenario: String? = nil, stageFailure: String? = nil) -> String {
        var program = build(uid: uid, home: home, operation: operation, digest: digest, bytes: bytes, requiredUID: uid, stageBase: stageBase, sourceOverride: source, osHome: false, expectedExit: expectedExit)
        if let waitScenario {
            precondition(["lost_child", "interrupt_once"].contains(waitScenario))
            let wrapper = "sub wait_observation { $!=0;my $got=waitpid($child,WNOHANG);my $status=$?;my $error=0+$!;return ($got,$status,$error); }"
            precondition(program.contains(wrapper))
            let replacement = waitScenario == "lost_child" ? "sub wait_observation { return (-1,0,ECHILD); }" : "my $fixture_interrupted=0;sub wait_observation { if(!$fixture_interrupted++){return (-1,0,EINTR);} $!=0;my $got=waitpid($child,WNOHANG);my $status=$?;my $error=0+$!;return ($got,$status,$error); }"
            program = program.replacingOccurrences(of: wrapper, with: replacement)
        }
        if let stageFailure {
            precondition(["unlink", "rmdir"].contains(stageFailure))
            if stageFailure == "unlink" { precondition(program.contains("elsif(unlink($leaf)!=1)")); program = program.replacingOccurrences(of: "elsif(unlink($leaf)!=1)", with: "elsif(0!=1)") }
            else { precondition(program.contains("!rmdir($dir)")); program = program.replacingOccurrences(of: "!rmdir($dir)", with: "1") }
        }
        return program
    }
    #endif
}
