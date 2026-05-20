import requests

PROVIDER_URLS = {
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "groq":     "https://api.groq.com/openai/v1/chat/completions",
    "openai":   "https://api.openai.com/v1/chat/completions",
}


class DeepseekClient:
    def __init__(self, provider, api_key, model,
                 backup_provider=None, backup_api_key=None, backup_model=None):
        self.provider        = provider
        self.api_key         = api_key
        self.model           = model
        self.backup_provider = backup_provider
        self.backup_api_key  = backup_api_key
        self.backup_model    = backup_model

    def _call(self, url: str, api_key: str, model: str, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       model,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens":  1024,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def chat(self, prompt: str) -> str:
        url = PROVIDER_URLS.get(self.provider, self.provider)
        try:
            return self._call(url, self.api_key, self.model, prompt)
        except Exception as primary_err:
            if self.backup_provider and self.backup_api_key:
                print(f"  Primary LLM failed ({primary_err}), trying backup...")
                backup_url = PROVIDER_URLS.get(self.backup_provider, self.backup_provider)
                return self._call(backup_url, self.backup_api_key, self.backup_model, prompt)
            raise primary_err
