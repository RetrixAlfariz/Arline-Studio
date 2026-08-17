from __future__ import annotations
from .lmstudio import LMStudioClient
from src.runtime_config import RuntimeConfig
class ModelManagementError(RuntimeError):pass
class LMStudioModelManager:
    def __init__(self,config:RuntimeConfig,rest_client=None):
        self.config=config;self.rest=rest_client or LMStudioClient(base_url=config.lmstudio.base_url,api_key=config.lmstudio.api_key,timeout_seconds=config.lmstudio.timeout_seconds)
    def status(self,key=None):
        key=key or self.config.lmstudio.model;info=self.rest.model_info(key)
        return {"model":key,"available":bool(info),"loaded":bool((info or {}).get("loaded_instances")),"loaded_instances":((info or {}).get("loaded_instances") or []),"max_context_length":(info or {}).get("max_context_length"),"reasoning":((info or {}).get("capabilities") or {}).get("reasoning"),"vision":bool(((info or {}).get("capabilities") or {}).get("vision")),"format":(info or {}).get("format")}
    def ensure_loaded(self):
        status=self.status()
        if status["loaded"]:return {"action":"reused",**status}
        if not self.config.lmstudio.auto_load:return {"action":"not_loaded",**status}
        return self.load_model()
    def reload_model(self):
        unloaded=self.rest.unload_model(self.config.lmstudio.model);result=self.load_model();result["action"]="reloaded";result["unloaded_instances"]=unloaded;return result
    def load_model(self):
        try:import lmstudio as lms
        except ImportError as exc:raise ModelManagementError("Install project dependencies to use GPU-aware LM Studio loading") from exc
        cfg={"contextLength":self.config.model_load.context_length,"gpu":{"ratio":self.config.model_load.gpu_ratio},"flashAttention":self.config.model_load.flash_attention}
        kwargs={}
        if self.config.lmstudio.api_key:kwargs["api_token"]=self.config.lmstudio.api_key
        try:
            client=lms.Client(self.rest.sdk_host,**kwargs)
            if hasattr(client,"__enter__"):
                with client as c:handle=c.llm.load_new_instance(self.config.lmstudio.model,config=cfg)
            else:
                handle=client.llm.load_new_instance(self.config.lmstudio.model,config=cfg);close=getattr(client,"close",None);close() if callable(close) else None
        except Exception as exc:raise ModelManagementError(f"Could not load model with GPU ratio {self.config.model_load.gpu_ratio:.2f}: {exc}") from exc
        return {"action":"loaded","model":self.config.lmstudio.model,"instance_id":str(getattr(handle,"identifier","") or "") or None,"gpu_ratio":self.config.model_load.gpu_ratio,"context_length":self.config.model_load.context_length}
