import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from argoslive.lan import Relay
from argoslive.web.server import DashboardServer


class LanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = DashboardServer(port=0)
        self.path = Path(self.tmp.name)/'session.json'
        self.path.write_text(json.dumps({'schema':'argos-desktop-session/1','url':self.backend.url}))
        os.chmod(self.path, 0o600)
        self.relay = Relay('127.0.0.1', 0, self.path)
        for server in [self.backend,self.relay]:
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        for server in [self.relay,self.backend]:
            server.shutdown(); server.server_close()
        self.tmp.cleanup()

    def request(self, path='/', method='GET', body=None, headers=None):
        conn=http.client.HTTPConnection('127.0.0.1', self.relay.server_port)
        conn.request(method,path,body=body,headers=headers or {})
        r=conn.getresponse(); result=(r.status,r.read(),dict(r.getheaders())); conn.close();return result

    def test_pair_requires_code_and_redirects_to_authenticated_dashboard(self):
        self.assertEqual(self.request()[0],200)
        self.assertEqual(self.request('/pair','POST','code=000')[0],403)
        status,_,headers=self.request('/pair','POST','code='+self.relay.code)
        self.assertEqual(status,303)
        self.assertEqual(self.request(headers['Location'])[0],200)

    def test_backend_authentication_and_origin_are_preserved(self):
        self.assertEqual(self.request('/app.js')[0],403)
        self.assertEqual(self.request('/app.js',headers={'X-Argos-Token':self.backend.token})[0],200)
        self.assertEqual(self.request('/app.js',headers={'Origin':'http://evil.example','X-Argos-Token':self.backend.token})[0],403)
        self.assertEqual(self.request('/app.js',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/lab/cancel?token='+self.backend.token,'POST','{}')[0],403)

    def test_pair_rate_limit(self):
        for _ in range(5):self.assertEqual(self.request('/pair','POST','code=no')[0],403)
        self.assertEqual(self.request('/pair','POST','code='+self.relay.code)[0],429)

    def test_desktop_restart_uses_new_session_token(self):
        self.backend.token='a'*43
        self.path.write_text(json.dumps({'schema':'argos-desktop-session/1','url':self.backend.url}))
        self.assertEqual(self.request('/app.js',headers={'X-Argos-Token':'a'*43})[0],200)


if __name__=='__main__':unittest.main()
