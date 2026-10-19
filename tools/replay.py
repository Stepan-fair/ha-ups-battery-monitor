"""Replay exported electrical history offline; never connects to a live HA."""
import argparse,csv,json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from custom_components.ups.models import EngineState,RawReading,RawSnapshot
from custom_components.ups.inputs import normalize
from custom_components.ups.engine import advance,resume
from custom_components.ups.profiles import validate_profile
from custom_components.ups.persistence import _encode,decode_state


def replay(config,trace,*,state=None):
    state=state or EngineState(config)
    if state.config!=config:raise ValueError('checkpoint profile differs')
    run_id=str(uuid4());state=resume(state,run_id=run_id)
    start=None;previous=None
    with Path(trace).open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            now=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
            if now.tzinfo is None or previous is not None and now<=previous:raise ValueError('ordered timezone-aware timestamps required')
            start=start or now;previous=now
            readings={}
            for key,column,unit in [('current','current_a','A'),('voltage','voltage_v','V'),('temperature','temperature_c','°C'),('grid_failed','grid_failed',None),('cutoff_flag','cutoff_flag',None)]:
                if row.get(column) not in (None,''):readings[key]=RawReading(row[column],unit,now)
            state=advance(state,normalize(RawSnapshot(now,(now-start).total_seconds(),run_id,readings),config.source)).state
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile',type=Path);parser.add_argument('trace',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    args=parser.parse_args()
    config=validate_profile(json.loads(args.profile.read_text(encoding='utf-8-sig')))
    state=decode_state(json.loads(args.checkpoint.read_text(encoding='utf-8-sig'))) if args.checkpoint else None
    result=replay(config,args.trace,state=state)
    print(json.dumps({'passport':_encode(result.passport),'last_discharge':_encode(result.last_discharge),
                      'prediction_errors':_encode(result.prediction_errors),'issues':result.issues},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
