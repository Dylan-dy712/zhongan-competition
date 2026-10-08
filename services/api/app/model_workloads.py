"""Documented workload settings for the configured official DeepSeek API."""
from urllib.parse import urlparse


def workload_options(base_url, model_id, workload):
    if not isinstance(base_url,str) or urlparse(base_url).hostname != 'api.deepseek.com':
        return {}
    if model_id != 'deepseek-flash':
        return {}
    if workload in {'extraction','narrative'}:
        return {'thinking':{'type':'disabled'}}
    if workload == 'review':
        return {'thinking':{'type':'enabled'},'reasoning_effort':'low'}
    return {}
