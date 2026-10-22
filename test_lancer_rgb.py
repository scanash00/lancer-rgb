import contextlib,io,json,pathlib,unittest
from unittest.mock import patch
import lancer_rgb as cli

class CapturedProtocolTests(unittest.TestCase):
 def test_matches_successful_vendor_calls(self):
  fixtures=json.loads(pathlib.Path(__file__).with_name('captured-static-fixtures.json').read_text())
  for name,color in [('red',(255,0,0)),('green',(0,255,0)),('blue',(0,0,255))]:
   with self.subTest(color=name):
    expected=[]
    for r in fixtures[name]:
     self.assertTrue(r['success'])
     word=r['function']=='Write_SMB_Word'
     v=r['value']
     # Observed CTI driver sends high byte first; Linux sends low byte first.
     if word:v=((v&255)<<8)|(v>>8)
     expected.append((r['arg1'],'word' if word else 'byte',r['arg2'],v))
    actual=[(x['address'],x['kind'],x['command'],x['value']) for x in cli.plan(color)]
    self.assertEqual(actual,expected)
 def test_wire_order_and_color_order(self):
  p=cli.plan((255,122,0),50,(0x71,))
  self.assertEqual(p[0]['value'].to_bytes(2,'little'),bytes([0x81,0x60]))
  self.assertEqual([x['value'] for x in p[1:4]],[128,0,61])
  self.assertEqual(len(p),34)
 def test_dry_run_never_opens_device(self):
  with patch.object(cli.os,'open',side_effect=AssertionError('device opened')):
   with contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(cli.main(['--color','FF0000']),0)
 def test_addresses_and_registers_are_restricted(self):
  p=cli.plan((0,0,0))
  self.assertEqual({x['address'] for x in p},{0x71,0x73})
  self.assertEqual({x['register'] for x in p if 'register' in x},{0x8160,0x8020,0x8029,0x802f})
if __name__=='__main__':unittest.main()
