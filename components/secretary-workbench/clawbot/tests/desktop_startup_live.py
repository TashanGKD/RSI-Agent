"""Opt-in installed Desktop launcher lifecycle check; no models or thread writes.

Uses the installed entry with only its private socket root replaced by a fixture.
Does not change HOME/CODEX_HOME, connect to the live control socket, or kill a
process unless its CLI command contains this fixture's exact socket path.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import queue
import shlex
import signal
import subprocess
import tempfile
import threading
import time

CLI = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
LIVE = Path('/var/lib/secretary-clawbot/desktop')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.print_help()
        return
    live_meta = (LIVE / 'engine.json').read_bytes()
    live_alias = os.readlink(LIVE / 'control.sock')
    original = (LIVE / 'codex-shared-entry').read_text()
    node = shlex.split(next(line for line in original.splitlines() if line.startswith('exec ')))[1]
    assert node == '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
    with tempfile.TemporaryDirectory(prefix='wx-boot-', dir='/private/tmp') as directory:
        root = Path(directory)
        root.chmod(0o700)
        entry = root / 'entry'
        lines = original.splitlines(keepends=True)
        lines = ['export TASHAN_DESKTOP_SOCKET_ROOT=' + shlex.quote(str(root)) + '\n'
                 if line.startswith('export TASHAN_DESKTOP_SOCKET_ROOT=') else line for line in lines]
        entry.write_text(''.join(lines))
        entry.chmod(0o700)
        children = []
        engines = set()

        def fixture_engine(pid):
            result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
            return result.returncode == 0 and result.stdout.strip().startswith(CLI + ' ') and ('unix://' + str(root / 'control.sock')) in result.stdout

        def stop_engine(pid, termination_signal=signal.SIGTERM):
            if fixture_engine(pid):
                os.kill(pid, termination_signal)

        def client(*, expect_shared=True, session=None):
            command = [str(entry), '-c', 'features.code_mode_host=true', 'app-server',
                       '--analytics-default-enabled', '-c',
                       'plugins.codex-app-tools@openai-bundled.mcp_servers.codex_app.enabled=true',
                       '-c', 'analytics.enabled=false']
            environment = dict(os.environ)
            if session is not None:
                environment['CODEX_APP_TOOLS_PIPE_PATH'] = session
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, env=environment)
            children.append(process)
            messages = queue.Queue()
            errors = collections.deque(maxlen=30)

            def read_output():
                for line in process.stdout:
                    try:
                        messages.put(json.loads(line))
                    except ValueError:
                        pass
                messages.put({'eof': True})

            def read_errors():
                for line in process.stderr:
                    errors.append(line[-1500:])

            threading.Thread(target=read_output, daemon=True).start()
            threading.Thread(target=read_errors, daemon=True).start()

            def call(number, method, params):
                process.stdin.write(json.dumps({'id': number, 'method': method, 'params': params}) + '\n')
                process.stdin.flush()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    reply = messages.get(timeout=max(.01, deadline - time.monotonic()))
                    if reply.get('eof'):
                        raise AssertionError('launcher exited: ' + ''.join(errors))
                    if reply.get('id') == number:
                        assert 'error' not in reply, reply.get('error')
                        return reply['result']
                raise AssertionError('native RPC timeout')

            initialized = call(1, 'initialize', {'clientInfo': {'name': 'desktop_startup_fixture', 'version': '1'}, 'capabilities': {'experimentalApi': True}})
            assert isinstance(initialized.get('userAgent'), str)
            process.stdin.write('{"method":"initialized","params":{}}\n')
            process.stdin.flush()
            assert call(2, 'thread/loaded/list', {})['data'] == [], 'fixture must have a separate engine'
            metadata = json.loads((root / 'engine.json').read_text())
            pid = metadata['enginePid']
            assert fixture_engine(pid), 'refusing non-fixture engine'
            engines.add(pid)
            assert metadata.get('socketAlias'), 'shared branch must publish pinned metadata'
            if expect_shared is not True:
                if expect_shared is False:
                    assert json.loads((root / 'bridge-state.json').read_text())['enabled'] is False
                assert fixture_engine(pid), 'fallback must leave the existing engine alone'
                return process, pid, call
            assert not any('official native startup' in line for line in errors), 'normal sharing unexpectedly fell back'
            descendants = subprocess.run(['/usr/bin/pgrep', '-P', str(process.pid)], capture_output=True, text=True)
            for child_pid in descendants.stdout.split():
                command = subprocess.run(['/bin/ps', '-p', child_pid, '-o', 'command='], capture_output=True, text=True).stdout.strip()
                if command.startswith(CLI + ' '):
                    assert fixture_engine(int(child_pid)), 'normal shared client launched independent stdio engine'
            return process, pid, call

        def close(process):
            process.stdin.close()
            assert process.wait(timeout=15) == 0

        def wait_dead(pid):
            deadline = time.monotonic() + 5
            while fixture_engine(pid) and time.monotonic() < deadline:
                time.sleep(.05)
            assert not fixture_engine(pid), 'fixture engine still running'

        try:
            first, first_pid, _ = client()
            close(first)
            wait_dead(first_pid)
            assert not (root / 'engine.json').exists()
            assert not (root / 'control.sock').is_symlink()
            second, second_pid, _ = client()
            assert second_pid != first_pid
            close(second)
            wait_dead(second_pid)
            # Exact previous failure: a dead engine and a dangling socket alias.
            (root / 'engine.json').write_text(json.dumps({'version': 1, 'enginePid': first_pid}))
            (root / 'engine.json').chmod(0o600)
            (root / 'control.sock').symlink_to('/private/tmp/codex-daemon-' + str(os.getuid()) + '/' + '0' * 64)
            third, third_pid, _ = client()
            assert third_pid not in (first_pid, second_pid)
            close(third)
            wait_dead(third_pid)
            # A frontend adapter disappearing must not cause a second engine.
            fourth, fourth_pid, _ = client()
            fourth.kill()
            fourth.wait(timeout=5)
            assert fixture_engine(fourth_pid)
            mismatch, _, _ = client(expect_shared=False, session='/private/tmp/fixture-new-desktop-pipe.sock')
            close(mismatch)
            assert fixture_engine(fourth_pid)
            fifth, fifth_pid, call = client()
            assert fifth_pid == fourth_pid
            assert json.loads((root / 'bridge-state.json').read_text())['enabled'] is True
            assert call(3, 'thread/loaded/list', {})['data'] == []
            close(fifth)
            assert fixture_engine(fourth_pid)
            stop_engine(fourth_pid)
            wait_dead(fourth_pid)
            # Two Desktop connection attempts must not race two shared engines.
            for _ in range(3):
                barrier = threading.Barrier(2)
                def simultaneous_client():
                    barrier.wait(timeout=3)
                    return client()
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(simultaneous_client) for _ in range(2)]
                    pair = [future.result(timeout=20) for future in futures]
                assert pair[0][1] == pair[1][1]
                owner_pid = int(subprocess.check_output(['/bin/ps', '-p', str(pair[0][1]), '-o', 'ppid='], text=True).strip())
                owner = next(item for item in pair if item[0].pid == owner_pid)
                other = next(item for item in pair if item is not owner)
                close(other[0]);close(owner[0]);wait_dead(owner[1])
            creator, creator_pid, _ = client()
            reuser, reuser_pid, reuse_call = client()
            assert creator_pid == reuser_pid
            creator.stdin.close()
            time.sleep(.1)
            assert creator.poll() is None, 'signed owner must stay alive for a reused Desktop'
            assert reuse_call(3, 'thread/loaded/list', {})['data'] == []
            close(reuser)
            assert creator.wait(timeout=10) == 0
            wait_dead(creator_pid)
            for attempt in range(3):
                barrier = threading.Barrier(2)
                def different_session(index):
                    barrier.wait(timeout=3)
                    return client(expect_shared=None, session='/private/tmp/session-' + str(attempt) + '-' + str(index) + '.sock')
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    pair = [future.result(timeout=20) for future in [pool.submit(different_session, i) for i in range(2)]]
                shared_pid = pair[0][1]
                parent = int(subprocess.check_output(['/bin/ps', '-p', str(shared_pid), '-o', 'ppid='], text=True).strip())
                owner = next(item for item in pair if item[0].pid == parent)
                fallback = next(item for item in pair if item is not owner)
                for _, _, rpc in pair:
                    assert rpc(3, 'thread/loaded/list', {})['data'] == []
                close(fallback[0]);close(owner[0]);wait_dead(shared_pid)
            # Once initialize has been forwarded, an engine failure must close
            # this connection rather than replaying input into a fresh engine.
            interrupted, interrupted_pid, _ = client()
            stop_engine(interrupted_pid, signal.SIGKILL)
            assert interrupted.wait(timeout=10) == 1
            wait_dead(interrupted_pid)
            if (root / 'engine.json').exists():
                assert json.loads((root / 'engine.json').read_text())['enginePid'] == interrupted_pid
            assert json.loads((root / 'bridge-state.json').read_text())['enabled'] is False
            recovered, recovered_pid, _ = client()
            close(recovered);wait_dead(recovered_pid)
            result = {'installed_signed_runtime': True, 'shared_branch_handshake': True,
                      'clean_shutdown_and_reopen': True, 'stale_metadata_and_dangling_alias_recovery': True,
                      'live_engine_reuse': True, 'concurrent_startup': True,
                      'stale_app_pipe_falls_back_and_pauses_bridge': True,
                      'post_traffic_failure_never_replayed_and_next_start_recovers': True,
                      'creator_eof_keeps_reused_desktop_alive': True,
                      'different_session_concurrency_preserves_both_connections': True,
                      'model_starts': 0, 'thread_writes': 0,
                      'production_app_tools_recovery': 'pending full authorized restart'}
        finally:
            for process in children:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for pid in engines:
                stop_engine(pid)
        assert hashlib.sha256(live_meta).digest() == hashlib.sha256((LIVE / 'engine.json').read_bytes()).digest()
        assert live_alias == os.readlink(LIVE / 'control.sock')
        result['production_engine_metadata_unchanged'] = True
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
