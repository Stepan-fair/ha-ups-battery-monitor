from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dataclasses import replace
from custom_components.ups.persistence import CheckpointStore
root=Path(sys.argv[1]);stage=int(sys.argv[2]);store=CheckpointStore(root,"entry1")
s=store.load().state
real_replace=os.replace;real_fsync=os.fsync
count=0
def barrier(fn):
 def wrapped(*args,**kw):
  global count
  result=fn(*args,**kw);count+=1
  if count==stage:os._exit(77)
  return result
 return wrapped
os.replace=barrier(real_replace)
os.fsync=barrier(real_fsync)
store.save(replace(s,discharge_ah_total=2))
os._exit(77)
