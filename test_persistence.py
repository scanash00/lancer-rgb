import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import lancer_service as service

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=patch.object(service,'STATE',Path(self.tmp.name)/'settings.json')
        p.start(); self.addCleanup(p.stop)

    def test_failed_write_preserves_saved_settings(self):
        original={'0x71':{'color':'FF0000','brightness':50}}
        service.save(original)
        with patch.object(service,'bus',return_value=6), patch.object(service.protocol,'apply',side_effect=OSError('bus failure')):
            with self.assertRaises(OSError): service.update('00FF00',75,'both')
        self.assertEqual(service.load(),original)

    def test_individual_sticks_survive_updates_and_restore(self):
        with patch.object(service,'bus',return_value=6), patch.object(service.protocol,'apply') as apply:
            service.update('FF0000',50,'both')
            service.update('000000',0,'0x73')
            self.assertEqual(service.load()['0x71']['color'],'FF0000')
            service.restore()
            operations=apply.call_args.args[1]
            self.assertEqual(operations,service.protocol.plan((255,0,0),50,(0x71,))+service.protocol.plan((0,0,0),0,(0x73,)))

    def test_preview_does_not_persist(self):
        original={'0x71':{'color':'FF0000','brightness':50}}
        service.save(original)
        with patch.object(service,'bus',return_value=6), patch.object(service.protocol,'apply') as apply:
            service.update('00FF00',25,'both',persist=False)
            apply.assert_called_once()
        self.assertEqual(service.load(),original)

    def test_readback_is_bounded_and_decodes_rbg(self):
        registers=[]
        def read(address,register):
            registers.append((address,register))
            if register==0x8020: return 0
            if register==0x8021: return 1
            return [128,32,64][(register-0x8160)%3]
        result=service.protocol.decode_snapshot(read)
        self.assertEqual(result['0x71']['colors'],['804020']*8)
        self.assertTrue(result['0x73']['static'])
        self.assertEqual(len(registers),52)
        self.assertEqual({a for a,r in registers},{0x71,0x73})
        self.assertEqual({r for a,r in registers},{0x8020,0x8021}|set(range(0x8160,0x8178)))

    def test_no_saved_state_means_no_bus_access(self):
        with patch.object(service,'bus',side_effect=AssertionError('accessed bus')):
            service.restore()

    def test_invalid_state_rejected_before_bus_access(self):
        service.STATE.write_text(json.dumps({'0x51':{'color':'FF0000','brightness':50}}))
        with patch.object(service,'bus',side_effect=AssertionError('accessed bus')):
            with self.assertRaises(ValueError): service.restore()

if __name__=='__main__': unittest.main()
