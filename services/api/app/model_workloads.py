"""Provider-specific settings and transport for production model workloads."""
from urllib.parse import urlparse
import threading
import time
import requests

_qianfan_lock = threading.Lock()
_qianfan_next_request = 0.0


def is_qianfan(base_url):
    return isinstance(base_url,str) and urlparse(base_url).hostname == 'qianfan.baidubce.com'


def uses_deepseek_strict(base_url,model_id):
    return isinstance(base_url,str) and urlparse(base_url).hostname == 'api.deepseek.com' and model_id == 'deepseek-flash'


def model_post(url, *, post, **kwargs):
    """Pace Qianfan requests and avoid inheriting unrelated proxy credentials."""
    global _qianfan_next_request
    if not is_qianfan(url):
        return post(url,**kwargs)
    with _qianfan_lock:
        time.sleep(max(0,_qianfan_next_request-time.monotonic()))
        _qianfan_next_request=time.monotonic()+1.1
    timeout=kwargs.get('timeout',45)
    kwargs['timeout']=(10,max(180,timeout[1] if isinstance(timeout,tuple) else timeout))
    with requests.Session() as session:
        session.trust_env=False
        return session.post(url,**kwargs)


def workload_options(base_url, model_id, workload):
    if is_qianfan(base_url) and model_id == 'glm-5.3-flash':
        return {'thinking':{'type':'enabled'},'reasoning_effort':'low','max_tokens':32768}
    if not isinstance(base_url,str) or urlparse(base_url).hostname != 'api.deepseek.com':
        return {}
    if model_id != 'deepseek-flash':
        return {}
    if workload in {'extraction','narrative','fidelity'}:
        return {'thinking':{'type':'disabled'}}
    if workload == 'review':
        return {'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    return {}
