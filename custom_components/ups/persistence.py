"""Checksummed, fsynced checkpoints with a separately durable previous generation."""
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from pathlib import Path
from types import UnionType
from typing import get_args,get_origin,get_type_hints
import hashlib,json,math,os,re,tempfile
from .models import EngineState
from .const import SCHEMA_VERSION

class CheckpointError(ValueError): pass
class CheckpointWriteError(OSError): pass
class UnsupportedVersion(CheckpointError): pass

@dataclass(frozen=True)
class SaveReceipt:
    generation: int
    checksum: str

@dataclass(frozen=True)
class RestoreResult:
    state: EngineState | None
    recovered_previous: bool
    issues: tuple[str,...]

def _encode(value):
    if is_dataclass(value):return {f.name:_encode(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,datetime):
        if value.tzinfo is None:raise CheckpointError("naive timestamp")
        return value.isoformat()
    if isinstance(value,(tuple,list)):return [_encode(v) for v in value]
    if isinstance(value,dict):return {k:_encode(v) for k,v in value.items()}
    return value

def _decode(t,value):
    origin=get_origin(t);args=get_args(t)
    if origin is UnionType:
        for option in args:
            try:return _decode(option,value)
            except (ValueError,TypeError,KeyError):pass
        raise CheckpointError("union field")
    if t is type(None):
        if value is not None:raise CheckpointError("expected null")
        return None
    if t is datetime:
        if not isinstance(value,str):raise CheckpointError("timestamp")
        result=datetime.fromisoformat(value)
        if result.tzinfo is None:raise CheckpointError("naive timestamp")
        return result
    if origin is tuple:
        if not isinstance(value,list):raise CheckpointError("tuple")
        if len(args)==2 and args[1] is Ellipsis:return tuple(_decode(args[0],v) for v in value)
        if len(args)!=len(value):raise CheckpointError("tuple size")
        return tuple(_decode(tp,v) for tp,v in zip(args,value))
    if origin is dict:
        if not isinstance(value,dict):raise CheckpointError("dict")
        return {_decode(args[0],k):_decode(args[1],v) for k,v in value.items()}
    if is_dataclass(t):
        if not isinstance(value,dict) or set(value)!={f.name for f in fields(t)}:raise CheckpointError("missing or unknown field")
        hints=get_type_hints(t)
        return t(**{k:_decode(hints[k],v) for k,v in value.items()})
    if t is float:
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise CheckpointError("finite number")
        return float(value)
    if t is int:
        if type(value) is not int:raise CheckpointError("integer")
        return value
    if t in (str,bool):
        if type(value) is not t:raise CheckpointError("scalar type")
        return value
    raise CheckpointError("unknown type")

def _canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")

def encode_state(state: EngineState,*,generation: int) -> dict:
    body={"version":SCHEMA_VERSION,"generation":generation,"state":_encode(replace(state,generation=generation))}
    return {**body,"checksum":hashlib.sha256(_canonical(body)).hexdigest()}

def decode_state(data: dict) -> EngineState:
    if not isinstance(data,dict):raise CheckpointError("envelope")
    if data.get("version") not in (1,SCHEMA_VERSION):raise UnsupportedVersion("unsupported_version")
    if set(data)!={"version","generation","state","checksum"}:raise CheckpointError("envelope fields")
    body={k:v for k,v in data.items() if k!="checksum"}
    if hashlib.sha256(_canonical(body)).hexdigest()!=data['checksum']:raise CheckpointError("checksum")
    payload=data['state']
    if data['version']==1:
        from .migration import upgrade_v1
        payload=upgrade_v1(payload)
    s=_decode(EngineState,payload)
    c=s.config;source=c.source
    if s.generation!=data['generation'] or s.generation<1:raise CheckpointError("generation")
    if not c.battery_id or not c.source.source_id or not 0<c.nominal_ah<=10000 or c.nominal_voltage<=0 or not 0<c.charge_efficiency<=1:raise CheckpointError("profile")
    if source.expected_interval_s<=0 or source.sign not in (-1,1) or not source.min_current_a<0<source.max_current_a:raise CheckpointError("source")
    if any(x<0 for x in (s.charge_ah_total,s.discharge_ah_total,s.charge_wh_total,s.discharge_wh_total)):raise CheckpointError("negative totals")
    for session in (s.active_session,s.last_charge,s.last_discharge,s.candidate_session,s.candidate_previous_session):
        if session and session.battery_id!=c.battery_id:raise CheckpointError("battery mismatch")
    return s

def _reject_constant(value):raise CheckpointError("nonfinite JSON")

class CheckpointStore:
    def __init__(self,root: Path,entry_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",entry_id):raise ValueError("entry_id must be a name")
        self.root=Path(root).resolve();self.directory=self.root/entry_id
        self.current=self.directory/"state.json";self.previous=self.directory/"state.previous.json"
        self._check_path()
    def _check_path(self):
        if not self.directory.resolve().is_relative_to(self.root):raise ValueError("checkpoint path escapes root")
    def _read(self,path):
        data=path.read_bytes()
        obj=json.loads(data,parse_constant=_reject_constant)
        return decode_state(obj),data
    def _scan(self):
        valid=[];issues=[];unsupported=False
        for path in (self.current,self.previous):
            if not path.exists():continue
            try:
                state,data=self._read(path);valid.append((state.generation,path,state,data))
            except UnsupportedVersion:unsupported=True;issues.append("unsupported_version")
            except (ValueError,TypeError,KeyError,OSError,OverflowError):issues.append("corrupt_checkpoint")
        valid.sort(key=lambda x:x[0],reverse=True)
        return valid,issues,unsupported
    def load(self) -> RestoreResult:
        self._check_path();valid,issues,unsupported=self._scan()
        if unsupported:return RestoreResult(None,False,("unsupported_version",))
        if not valid:return RestoreResult(None,False,tuple(dict.fromkeys(issues)))
        _,path,state,_=valid[0]
        recovered=path==self.previous
        return RestoreResult(state,recovered,tuple(dict.fromkeys(issues+(["recovered_previous"] if recovered else []))))
    def _fsync_directory(self):
        if os.name=="posix":
            fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    def _atomic(self,target,data):
        fd,name=tempfile.mkstemp(prefix=".checkpoint-",suffix=".tmp",dir=self.directory)
        try:
            with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(name,target)
            self._fsync_directory()
        finally:
            try:os.unlink(name)
            except FileNotFoundError:pass
    def save(self,state: EngineState) -> SaveReceipt:
        try:
            self._check_path();valid,issues,unsupported=self._scan()
            if unsupported or (issues and not valid):raise CheckpointError("refuse overwrite of unrestorable checkpoint")
            generation=max([state.generation]+[x[0] for x in valid])+1
            encoded=encode_state(state,generation=generation)
            # Validate every field before replacing either generation.
            decode_state(encoded)
            self.directory.mkdir(parents=True,exist_ok=True)
            if valid:self._atomic(self.previous,valid[0][3])
            self._atomic(self.current,_canonical(encoded))
            return SaveReceipt(generation,encoded['checksum'])
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as e:
            raise CheckpointWriteError(str(e)) from e
