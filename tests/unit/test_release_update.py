from pathlib import Path
import subprocess,sys
from tools.build_release import build_release


def test_component_archive_can_run_its_pure_engine_in_isolation(tmp_path):
    archive=tmp_path/'ups.zip'
    build_release(Path(__file__).parents[2],archive)
    script="import sys; sys.path.insert(0,sys.argv[1]); from custom_components.ups.engine import advance; from custom_components.ups.prediction import assessment; from custom_components.ups.migration import upgrade_config; print('ok')"
    result=subprocess.run([sys.executable,'-I','-c',script,str(archive)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='ok'
