"""Trapezoid terminal flows; zero crossings are separate lobes."""
from .models import Sample, IntervalCharge

def integrate(start: Sample,end: Sample,efficiency: float) -> IntervalCharge:
    dt=end.monotonic_s-start.monotonic_s
    if dt<=0 or start.run_id!=end.run_id or start.source_id!=end.source_id: return IntervalCharge()
    points=[(0,start.current_a,start.voltage_v)]
    if start.current_a*end.current_a<0:
        f=-start.current_a/(end.current_a-start.current_a)
        points.append((dt*f,0,start.voltage_v+(end.voltage_v-start.voltage_v)*f))
    points.append((dt,end.current_a,end.voltage_v))
    ca=da=cw=dw=0.0
    for (t0,i0,v0),(t1,i1,v1) in zip(points,points[1:]):
        h=(t1-t0)/3600
        ah=(i0+i1)*.5*h; wh=(v0*i0+v1*i1)*.5*h
        if ah>=0:ca+=ah;cw+=wh
        else:da-=ah;dw-=wh
    return IntervalCharge(dt,ca,da,cw,dw,efficiency*ca-da)
