"""Documented workload settings for the configured official DeepSeek API."""
from urllib.parse import urlparse


def workload_options(base_url, model_id, workload):
    if isinstance(base_url, str) and urlparse(base_url).hostname == 'qianfan.baidubce.com' and model_id in {'glm-5.3', 'glm-5.3-flash'}:
        # Qianfan GLM-5.3 models require thinking; bound reasoning + answer size.
        return {'thinking': {'type': 'enabled'}, 'max_tokens': 32768}
    if not isinstance(base_url,str) or urlparse(base_url).hostname != 'api.deepseek.com':
        return {}
    if model_id != 'deepseek-flash':
        return {}
    if workload in {'extraction','narrative','fidelity'}:
        return {'thinking':{'type':'disabled'}}
    if workload == 'review':
        return {'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    return {}
