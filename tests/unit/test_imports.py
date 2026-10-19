import subprocess,sys

def test_pure_import_needs_no_homeassistant():
    code="""import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.startswith('homeassistant'): raise RuntimeError('HA import forbidden')
sys.meta_path.insert(0,Block())
import custom_components.ups.inputs,custom_components.ups.profiles
"""
    r=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
