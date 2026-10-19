"""Build a component-only archive and a separate SHA-256 file manifest."""
from pathlib import Path
import argparse,hashlib,json,zipfile

ROOT_PY={'__init__.py','const.py','models.py','profiles.py','inputs.py','accounting.py','sessions.py','engine.py','capacity.py','forecast.py','persistence.py','runtime.py','sensor.py','binary_sensor.py','config_flow.py','diagnostics.py','activity.py'}

def allowed_component_file(relative):
    p=Path(relative)
    return len(p.parts)==1 and (p.name in ROOT_PY or p.name in {'manifest.json','strings.json'}) or len(p.parts)==2 and p.parts[0]=='translations' and p.suffix=='.json'

def build_release(source_root: Path,output_zip: Path) -> dict[str,str]:
    source=(Path(source_root)/'custom_components/ups').resolve()
    output_zip=Path(output_zip)
    if not source.is_dir():raise ValueError('component directory missing')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('domain')!='ups':raise ValueError('unexpected component domain')
    files=[]
    for f in sorted(source.rglob('*')):
        if not f.is_file() or not allowed_component_file(f.relative_to(source)):continue
        if f.is_symlink() or not f.resolve().is_relative_to(source):raise ValueError('symlink in release')
        files.append((f,'custom_components/ups/'+f.relative_to(source).as_posix()))
    output_zip.parent.mkdir(parents=True,exist_ok=True)
    hashes={}
    with zipfile.ZipFile(output_zip,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f,name in files:
            data=f.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
    output_zip.with_suffix('.sha256.json').write_text(json.dumps(hashes,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return hashes

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    hashes=build_release(args.source,args.output);print(json.dumps({'archive':str(args.output),'files':len(hashes)}))
