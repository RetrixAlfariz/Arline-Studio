from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import RLock
from typing import Any,Callable
log=logging.getLogger(__name__)
@dataclass(frozen=True,slots=True)
class DomainEvent:
 name:str
 database_path:str
 payload:dict[str,Any]
class DomainEventBus:
 def __init__(self,database_path:str): self.database_path=database_path;self._lock=RLock();self._handlers={}
 def subscribe(self,name:str,handler:Callable[[DomainEvent],None],*,key:str|None=None):
  key=key or f"{handler.__module__}.{getattr(handler,'__qualname__',handler.__name__)}"
  with self._lock:self._handlers.setdefault(name,{})[key]=handler
 def emit(self,name:str,payload:dict[str,Any]|None=None):
  event=DomainEvent(name,self.database_path,dict(payload or {}))
  with self._lock:handlers=list(self._handlers.get(name,{}).items())
  errors=[]
  for key,handler in handlers:
   try:handler(event)
   except Exception as exc:errors.append(exc);log.exception("Domain event handler %s failed for %s",key,name)
  return errors
_registry_lock=RLock();_registry={}
def _key(p):return str(Path(p).expanduser().resolve())
def get_domain_event_bus(p):
 k=_key(p)
 with _registry_lock:
  if k not in _registry:_registry[k]=DomainEventBus(k)
  return _registry[k]
def emit_domain_event(p,name,payload=None):return get_domain_event_bus(p).emit(name,payload)
def clear_domain_event_bus(p):
 with _registry_lock:_registry.pop(_key(p),None)
