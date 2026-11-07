from pathlib import Path
import re
import shutil
import subprocess

def bundle_native(destination):
    destination.mkdir(parents=True, exist_ok=True)
    roots = [Path(shutil.which('node')).resolve(), Path('/opt/homebrew/bin/ffmpeg').resolve()]
    originals = {}
    def resolve(dependency, original):
        if dependency.startswith('@loader_path/'): dependency = str(original.parent / dependency[len('@loader_path/'):])
        if dependency.startswith('@rpath/'):
            local = original.parent / dependency[len('@rpath/'):]
            if local.exists(): dependency = str(local)
            else: raise RuntimeError('Unresolved native dependency: '+dependency)
        return Path(dependency).resolve()
    queue = list(roots)
    while queue:
        original = queue.pop(0).resolve()
        name = original.name
        if name in originals:
            if originals[name] != original: raise RuntimeError('Native dependency filename collision: '+name)
            continue
        originals[name] = original
        dependencies = subprocess.check_output(['/usr/bin/otool','-L',str(original)], text=True).splitlines()[1:]
        for entry in dependencies:
            dependency = entry.strip().split(' (',1)[0]
            if dependency.startswith(('/System/', '/usr/lib/')): continue
            dependency_path = resolve(dependency, original)
            if dependency_path != original: queue.append(dependency_path)
    for name, original in originals.items():
        target = destination/name
        if target.exists(): target.chmod(target.stat().st_mode | 0o200)
        shutil.copy2(original, target)
    for name, original in originals.items():
        target = destination/name
        dependencies = subprocess.check_output(['/usr/bin/otool','-L',str(original)], text=True).splitlines()[1:]
        for entry in dependencies:
            dependency = entry.strip().split(' (',1)[0]
            if dependency.startswith(('/System/', '/usr/lib/')): continue
            replacement = '@loader_path/'+resolve(dependency, original).name
            subprocess.run(['/usr/bin/install_name_tool','-change',dependency,replacement,str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if target.suffix == '.dylib': subprocess.run(['/usr/bin/install_name_tool','-id','@loader_path/'+name,str(target)],check=True)
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(target)],check=True,stderr=subprocess.DEVNULL)
