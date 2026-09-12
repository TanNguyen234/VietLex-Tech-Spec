import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import truststore
truststore.inject_into_ssl()
import dns.resolver
original_init = dns.resolver.Resolver.__init__
def use_doh(self, *args, **kwargs):
    original_init(self, configure=False)
    self.nameservers = ['https://1.1.1.1/dns-query']
dns.resolver.Resolver.__init__ = use_doh
dns.resolver.default_resolver = dns.resolver.Resolver()
import uvicorn
uvicorn.run('app.main:app',host='127.0.0.1',port=8766)
