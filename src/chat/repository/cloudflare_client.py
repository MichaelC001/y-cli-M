import json
from typing import Any
import httpx
from config import config

class CloudflareClient:
    """Client for interacting with Cloudflare KV and R2"""
    
    def __init__(self):
        self.account_id = config.get('cloudflare', {}).get('account_id')
        self.api_token = config.get('cloudflare', {}).get('api_token')
        self.kv_namespace_id = config.get('cloudflare', {}).get('kv_namespace_id')
        self.r2_bucket_name = config.get('cloudflare', {}).get('r2_bucket_name')
        
        if not all([self.account_id, self.api_token, self.kv_namespace_id]):
            raise ValueError("Cloudflare configuration is incomplete. Please check your config.")
        
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
    async def kv_get(self, key: str) -> Any:
        """Get a value from KV namespace"""
        url = f"{self.base_url}/storage/kv/namespaces/{self.kv_namespace_id}/values/{key}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            
            return response.text
    
    async def kv_put(self, key: str, value: Any) -> bool:
        """Put a value into KV namespace"""
        url = f"{self.base_url}/storage/kv/namespaces/{self.kv_namespace_id}/values/{key}"
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url, 
                headers=self.headers,
                content=value
            )
            
            response.raise_for_status()
            return response.json().get('success', False)
    
    async def r2_get(self, key: str) -> Any:
        """Get an object from R2 bucket (via Workers API)"""
        # Note: Direct R2 API access requires a Worker or pre-signed URL
        # This is a simplified example assuming a Worker exists
        url = f"{self.base_url}/r2/buckets/{self.r2_bucket_name}/objects/{key}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            
            return response.text
    
    async def r2_put(self, key: str, value: Any) -> bool:
        """Put an object into R2 bucket (via Workers API)"""
        # Note: Direct R2 API access requires a Worker or pre-signed URL
        # This is a simplified example assuming a Worker exists
        url = f"{self.base_url}/r2/buckets/{self.r2_bucket_name}/objects/{key}"
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url, 
                headers=self.headers,
                content=value
            )
            
            if response.status_code == 404:
                return False
            
            response.raise_for_status()
            return True
