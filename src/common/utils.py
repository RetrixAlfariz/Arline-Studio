from __future__ import annotations
import copy, re

MONTHS={"januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,"juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12}
COLORS={"merah muda":"pink","abu-abu":"gray","hitam":"black","putih":"white","merah":"red","biru":"blue","navy":"navy","ungu":"purple","pink":"pink","hijau":"green","kuning":"yellow","coklat":"brown","abu":"gray","magenta":"magenta","burgundy":"burgundy","lavender":"lavender","mocca":"mocha"}

def clean(v): return int(round(v)) if abs(v-round(v))<1e-9 else round(v,4)
def cm(v,u): return v*100 if u.lower() in {'m','meter','metre'} else v
def clamp(v,a=0,b=1): return max(a,min(b,float(v)))
def dcopy(x): return copy.deepcopy(x)
def getp(d,path,default=None):
    cur=d
    for k in path.split('.'):
        if not isinstance(cur,dict) or k not in cur: return default
        cur=cur[k]
    return cur
def setp(d,path,val):
    cur=d; parts=path.split('.')
    for k in parts[:-1]: cur=cur.setdefault(k,{})
    cur[parts[-1]]=val
